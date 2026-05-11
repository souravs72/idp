# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 22 — Multilingual keyword dictionary for the rule mapper.

The legacy :class:`idp.mappers.mapper.FieldMapper` ships English-only
keyword aliases per DocType.  Phase 22 lets users upload documents in any
of the languages supported by PaddleOCR; we still need to recognise
"Invoice Date", "तारीख", "تاريخ الفاتورة", "发票日期" as the **same**
``posting_date`` field.

This module provides two things:

1. ``FIELD_KEYWORDS_MULTILINGUAL`` — a per-DocType, per-language map of
   field aliases for the top-12 PaddleOCR languages.
2. :func:`merge_keywords_for_languages` — produce a flattened
   ``{fieldname: [aliases]}`` dict that the rule mapper can drop straight
   into its existing keyword-matching loop.

Design notes
------------
* The English column reuses the same vocabulary as
  :data:`FieldMapper.FIELD_KEYWORDS` to guarantee zero regression for
  English documents (we just intersect-merge when callers ask for
  ``["en", ...]``).
* Keys are :pep:`8` ``fieldname`` strings (snake_case ERPNext fieldnames)
  — never display labels — so the mapper can map directly.
* Language codes follow PaddleOCR's two-letter codes
  (``en``, ``hi``, ``ar``, ``ch``, ``fr``, ``de``, ``ja``, ``ko``,
  ``es``, ``pt``, ``ta``, ``te``).
* Aliases are lower-cased and stripped at lookup time by
  :func:`merge_keywords_for_languages` so the source dict can stay in
  natural casing for readability.
* New DocTypes / fields can be added without touching the rule mapper —
  unknown DocTypes silently fall back to whatever the rule mapper has in
  its English table.
"""

from __future__ import annotations

from collections.abc import Iterable

from idp.core.logger import get_logger

logger = get_logger("idp.mappers.keywords_ml")


# Supported PaddleOCR language codes (top 12 by typical demand for
# accounting documents).  Used by :func:`is_supported_language` and the
# OCR engine's ``detect_language`` heuristic.
SUPPORTED_LANGUAGES: tuple[str, ...] = (
	"en",
	"hi",
	"ar",
	"ch",
	"fr",
	"de",
	"ja",
	"ko",
	"es",
	"pt",
	"ta",
	"te",
)

# Convenience aliases for the few non-PaddleOCR codes users sometimes
# pass (ISO 639-1 vs PaddleOCR codes).  Anything not listed here is
# returned unchanged by :func:`normalize_language`.
_LANGUAGE_ALIASES: dict[str, str] = {
	"english": "en",
	"hindi": "hi",
	"arabic": "ar",
	"chinese": "ch",
	"zh": "ch",
	"zh-cn": "ch",
	"zh-hans": "ch",
	"french": "fr",
	"german": "de",
	"japanese": "ja",
	"korean": "ko",
	"spanish": "es",
	"portuguese": "pt",
	"tamil": "ta",
	"telugu": "te",
}


def normalize_language(code: str | None) -> str:
	"""Best-effort normalisation to a PaddleOCR language code.

	Falls back to ``"en"`` when *code* is empty / unknown so callers
	never have to worry about ``None`` propagating into PaddleOCR.
	"""

	if not code:
		return "en"
	c = str(code).strip().lower()
	if c in SUPPORTED_LANGUAGES:
		return c
	if c in _LANGUAGE_ALIASES:
		return _LANGUAGE_ALIASES[c]
	# Strip BCP-47 region tags like "pt-BR" → "pt" if the base matches.
	base = c.split("-", 1)[0]
	if base in SUPPORTED_LANGUAGES:
		return base
	if base in _LANGUAGE_ALIASES:
		return _LANGUAGE_ALIASES[base]
	return "en"


def is_supported_language(code: str | None) -> bool:
	"""Return ``True`` when *code* matches a shipped language entry.

	Unlike :func:`normalize_language`, this never silently maps an
	unknown input to ``"en"`` — it returns ``False`` so callers can
	tell whether the user asked for a language we don't yet ship.
	"""

	if not code:
		return False
	c = str(code).strip().lower()
	if c in SUPPORTED_LANGUAGES:
		return True
	if c in _LANGUAGE_ALIASES:
		return True
	base = c.split("-", 1)[0]
	return base in SUPPORTED_LANGUAGES or base in _LANGUAGE_ALIASES


# ---------------------------------------------------------------------------
# Multilingual aliases per DocType.
#
# Only **header** fields are translated — line-item column headers vary
# wildly across vendors and are usually rendered in English even on
# non-English templates.  Where a translation isn't yet curated we fall
# back to the English aliases (handled in ``merge_keywords_for_languages``).
# ---------------------------------------------------------------------------

FIELD_KEYWORDS_MULTILINGUAL: dict[str, dict[str, dict[str, list[str]]]] = {
	"Purchase Invoice": {
		"supplier": {
			"en": ["supplier", "vendor", "seller", "bill from", "sold by"],
			"hi": ["आपूर्तिकर्ता", "विक्रेता", "विक्रय कर्ता"],
			"ar": ["المورد", "البائع", "اسم المورد"],
			"ch": ["供应商", "卖方", "供货商"],
			"fr": ["fournisseur", "vendeur", "facturé par"],
			"de": ["lieferant", "verkäufer", "rechnungssteller"],
			"ja": ["仕入先", "サプライヤー", "販売者"],
			"ko": ["공급자", "공급업체", "판매자"],
			"es": ["proveedor", "vendedor", "facturado por"],
			"pt": ["fornecedor", "vendedor", "faturado por"],
			"ta": ["விற்பனையாளர்", "வழங்குநர்"],
			"te": ["సరఫరాదారు", "విక్రేత"],
		},
		"posting_date": {
			"en": ["invoice date", "bill date", "dated", "inv date"],
			"hi": ["दिनांक", "तारीख", "चालान दिनांक", "बिल तारीख"],
			"ar": ["تاريخ الفاتورة", "التاريخ", "تاريخ"],
			"ch": ["发票日期", "日期", "开票日期"],
			"fr": ["date de facture", "date", "date facture"],
			"de": ["rechnungsdatum", "datum", "belegdatum"],
			"ja": ["請求日", "日付", "発行日"],
			"ko": ["청구 일자", "날짜", "발행일"],
			"es": ["fecha de factura", "fecha"],
			"pt": ["data da fatura", "data"],
			"ta": ["விலைப்பட்டியல் தேதி", "தேதி"],
			"te": ["ఇన్‌వాయిస్ తేదీ", "తేదీ"],
		},
		"due_date": {
			"en": ["due date", "payment due", "due by", "pay by"],
			"hi": ["देय तिथि", "भुगतान देय"],
			"ar": ["تاريخ الاستحقاق", "تاريخ السداد"],
			"ch": ["到期日", "付款到期日"],
			"fr": ["date d'échéance", "à payer avant"],
			"de": ["fälligkeitsdatum", "zahlbar bis"],
			"ja": ["支払期日", "期日"],
			"ko": ["만기일", "지불 기한"],
			"es": ["fecha de vencimiento", "vence el"],
			"pt": ["data de vencimento", "vence em"],
			"ta": ["நிலுவை தேதி"],
			"te": ["చెల్లింపు తేదీ"],
		},
		"bill_no": {
			"en": ["invoice no", "invoice number", "bill no", "inv no", "ref no"],
			"hi": ["चालान संख्या", "बिल संख्या", "इन्वॉइस नंबर"],
			"ar": ["رقم الفاتورة", "رقم"],
			"ch": ["发票号", "发票编号", "账单号"],
			"fr": ["n° de facture", "numéro de facture", "facture n°"],
			"de": ["rechnungsnummer", "rechnungs-nr", "beleg-nr"],
			"ja": ["請求書番号", "インボイス番号"],
			"ko": ["청구서 번호", "송장 번호"],
			"es": ["número de factura", "n° factura", "factura n°"],
			"pt": ["número da fatura", "fatura nº"],
			"ta": ["விலைப்பட்டியல் எண்"],
			"te": ["ఇన్‌వాయిస్ నంబర్"],
		},
		"taxes_and_charges": {
			"en": ["tax", "vat", "gst", "tax amount", "tax total"],
			"hi": ["कर", "जीएसटी", "टैक्स"],
			"ar": ["ضريبة", "ضريبة القيمة المضافة"],
			"ch": ["税", "增值税", "税额"],
			"fr": ["taxe", "tva", "montant taxe"],
			"de": ["steuer", "mwst", "umsatzsteuer", "ust"],
			"ja": ["税", "消費税", "税額"],
			"ko": ["세금", "부가세", "세액"],
			"es": ["impuesto", "iva", "importe impuesto"],
			"pt": ["imposto", "iva", "valor imposto"],
			"ta": ["வரி", "ஜி.எஸ்.டி"],
			"te": ["పన్ను", "జీఎస్‌టీ"],
		},
		"net_total": {
			"en": ["subtotal", "sub total", "net total", "net amount"],
			"hi": ["उप योग", "शुद्ध कुल", "नेट राशि"],
			"ar": ["المجموع الفرعي", "الصافي"],
			"ch": ["小计", "净额", "未税金额"],
			"fr": ["sous-total", "total net", "montant net"],
			"de": ["zwischensumme", "nettobetrag", "netto"],
			"ja": ["小計", "純額"],
			"ko": ["소계", "공급 가액"],
			"es": ["subtotal", "importe neto"],
			"pt": ["subtotal", "valor líquido"],
			"ta": ["துணை மொத்தம்"],
			"te": ["ఉప మొత్తం"],
		},
		"grand_total": {
			"en": ["grand total", "total amount", "amount due", "balance due"],
			"hi": ["कुल राशि", "महायोग", "देय राशि"],
			"ar": ["الإجمالي", "المجموع الكلي", "الإجمالي المستحق"],
			"ch": ["合计", "总计", "应付金额"],
			"fr": ["total général", "montant total", "à payer"],
			"de": ["gesamtbetrag", "endbetrag", "zu zahlen"],
			"ja": ["合計", "総額", "請求金額"],
			"ko": ["총계", "총금액", "청구 금액"],
			"es": ["total general", "importe total", "total a pagar"],
			"pt": ["total geral", "valor total", "total a pagar"],
			"ta": ["மொத்த தொகை"],
			"te": ["మొత్తం"],
		},
		"remarks": {
			"en": ["remarks", "notes", "memo", "comments"],
			"hi": ["टिप्पणी", "नोट"],
			"ar": ["ملاحظات"],
			"ch": ["备注", "说明"],
			"fr": ["remarques", "notes"],
			"de": ["bemerkungen", "anmerkungen", "notiz"],
			"ja": ["備考", "メモ"],
			"ko": ["비고", "메모"],
			"es": ["observaciones", "notas"],
			"pt": ["observações", "notas"],
			"ta": ["குறிப்பு"],
			"te": ["గమనికలు"],
		},
		"terms": {
			"en": ["terms", "terms and conditions", "payment terms"],
			"hi": ["शर्तें", "नियम और शर्तें", "भुगतान शर्तें"],
			"ar": ["الشروط", "الشروط والأحكام"],
			"ch": ["条款", "条款及条件", "付款条件"],
			"fr": ["conditions", "conditions de paiement"],
			"de": ["bedingungen", "zahlungsbedingungen", "agb"],
			"ja": ["条件", "支払条件"],
			"ko": ["약관", "지불 조건"],
			"es": ["términos", "condiciones de pago"],
			"pt": ["termos", "condições de pagamento"],
			"ta": ["விதிமுறைகள்"],
			"te": ["నిబంధనలు"],
		},
		"currency": {
			"en": ["currency"],
			"hi": ["मुद्रा"],
			"ar": ["العملة"],
			"ch": ["货币"],
			"fr": ["devise", "monnaie"],
			"de": ["währung"],
			"ja": ["通貨"],
			"ko": ["통화"],
			"es": ["moneda"],
			"pt": ["moeda"],
			"ta": ["நாணயம்"],
			"te": ["కరెన్సీ"],
		},
	},
	"Sales Invoice": {
		"customer": {
			"en": ["customer", "buyer", "client", "bill to", "sold to"],
			"hi": ["ग्राहक", "खरीदार", "बिल टू"],
			"ar": ["العميل", "المشتري", "اسم العميل"],
			"ch": ["客户", "买方", "购买方"],
			"fr": ["client", "acheteur", "facturer à"],
			"de": ["kunde", "käufer", "rechnung an"],
			"ja": ["顧客", "買い手", "請求先"],
			"ko": ["고객", "구매자", "청구처"],
			"es": ["cliente", "comprador", "facturar a"],
			"pt": ["cliente", "comprador", "faturar a"],
			"ta": ["வாடிக்கையாளர்"],
			"te": ["కస్టమర్"],
		},
		"posting_date": {
			"en": ["invoice date", "bill date", "dated", "inv date"],
			"hi": ["चालान दिनांक", "दिनांक"],
			"ar": ["تاريخ الفاتورة", "التاريخ"],
			"ch": ["发票日期", "日期"],
			"fr": ["date de facture", "date"],
			"de": ["rechnungsdatum", "datum"],
			"ja": ["請求日", "日付"],
			"ko": ["청구 일자", "날짜"],
			"es": ["fecha de factura"],
			"pt": ["data da fatura"],
			"ta": ["தேதி"],
			"te": ["తేదీ"],
		},
		"due_date": {
			"en": ["due date", "payment due", "due by"],
			"hi": ["देय तिथि"],
			"ar": ["تاريخ الاستحقاق"],
			"ch": ["到期日", "付款到期日"],
			"fr": ["date d'échéance"],
			"de": ["fälligkeitsdatum"],
			"ja": ["支払期日"],
			"ko": ["만기일"],
			"es": ["fecha de vencimiento"],
			"pt": ["data de vencimento"],
		},
		"po_no": {
			"en": ["po no", "po number", "purchase order", "your order"],
			"hi": ["क्रय आदेश", "पीओ नंबर"],
			"ar": ["رقم أمر الشراء"],
			"ch": ["采购订单号", "订单号"],
			"fr": ["n° de commande", "bon de commande"],
			"de": ["bestell-nr", "bestellnummer"],
			"ja": ["発注番号", "注文番号"],
			"ko": ["주문 번호", "구매 주문"],
			"es": ["número de pedido", "orden de compra"],
			"pt": ["número do pedido", "ordem de compra"],
		},
		"taxes_and_charges": {
			"en": ["tax", "vat", "gst", "tax amount"],
			"hi": ["कर", "जीएसटी"],
			"ar": ["ضريبة"],
			"ch": ["税", "税额"],
			"fr": ["taxe", "tva"],
			"de": ["steuer", "mwst"],
			"ja": ["税", "消費税"],
			"ko": ["세금", "부가세"],
			"es": ["impuesto", "iva"],
			"pt": ["imposto", "iva"],
		},
		"net_total": {
			"en": ["subtotal", "sub total", "net total"],
			"hi": ["उप योग", "नेट कुल"],
			"ar": ["المجموع الفرعي"],
			"ch": ["小计", "净额"],
			"fr": ["sous-total", "total net"],
			"de": ["zwischensumme", "nettobetrag"],
			"ja": ["小計"],
			"ko": ["소계"],
			"es": ["subtotal"],
			"pt": ["subtotal"],
		},
		"grand_total": {
			"en": ["grand total", "total amount"],
			"hi": ["कुल राशि", "महायोग"],
			"ar": ["الإجمالي"],
			"ch": ["合计", "总计"],
			"fr": ["total général", "montant total"],
			"de": ["gesamtbetrag"],
			"ja": ["合計", "総額"],
			"ko": ["총계", "총금액"],
			"es": ["total general"],
			"pt": ["total geral"],
		},
		"currency": {
			"en": ["currency"],
			"hi": ["मुद्रा"],
			"ar": ["العملة"],
			"ch": ["货币"],
			"fr": ["devise"],
			"de": ["währung"],
			"ja": ["通貨"],
			"ko": ["통화"],
			"es": ["moneda"],
			"pt": ["moeda"],
		},
	},
	"Purchase Order": {
		"supplier": {
			"en": ["supplier", "vendor", "seller"],
			"hi": ["आपूर्तिकर्ता", "विक्रेता"],
			"ar": ["المورد", "البائع"],
			"ch": ["供应商", "卖方"],
			"fr": ["fournisseur", "vendeur"],
			"de": ["lieferant", "verkäufer"],
			"ja": ["仕入先", "サプライヤー"],
			"ko": ["공급자", "공급업체"],
			"es": ["proveedor", "vendedor"],
			"pt": ["fornecedor", "vendedor"],
		},
		"transaction_date": {
			"en": ["order date", "po date", "dated"],
			"hi": ["आदेश दिनांक", "पीओ दिनांक"],
			"ar": ["تاريخ الأمر", "تاريخ"],
			"ch": ["订单日期", "采购日期"],
			"fr": ["date de commande"],
			"de": ["bestelldatum"],
			"ja": ["発注日"],
			"ko": ["주문 일자"],
			"es": ["fecha de pedido"],
			"pt": ["data do pedido"],
		},
		"schedule_date": {
			"en": ["delivery date", "expected date", "required by"],
			"hi": ["वितरण तिथि", "डिलीवरी की तारीख"],
			"ar": ["تاريخ التسليم"],
			"ch": ["交货日期"],
			"fr": ["date de livraison"],
			"de": ["lieferdatum", "liefertermin"],
			"ja": ["納品日", "納期"],
			"ko": ["배송 일자", "납기일"],
			"es": ["fecha de entrega"],
			"pt": ["data de entrega"],
		},
		"net_total": {
			"en": ["subtotal", "sub total", "net total"],
			"hi": ["उप योग"],
			"ar": ["المجموع الفرعي"],
			"ch": ["小计"],
			"fr": ["sous-total"],
			"de": ["zwischensumme", "nettobetrag"],
			"ja": ["小計"],
			"ko": ["소계"],
			"es": ["subtotal"],
			"pt": ["subtotal"],
		},
		"grand_total": {
			"en": ["grand total", "total amount"],
			"hi": ["कुल राशि"],
			"ar": ["الإجمالي"],
			"ch": ["合计", "总计"],
			"fr": ["total général"],
			"de": ["gesamtbetrag"],
			"ja": ["合計"],
			"ko": ["총계"],
			"es": ["total general"],
			"pt": ["total geral"],
		},
		"currency": {
			"en": ["currency"],
			"hi": ["मुद्रा"],
			"ar": ["العملة"],
			"ch": ["货币"],
			"fr": ["devise"],
			"de": ["währung"],
			"ja": ["通貨"],
			"ko": ["통화"],
			"es": ["moneda"],
			"pt": ["moeda"],
		},
	},
	"Sales Order": {
		"customer": {
			"en": ["customer", "buyer", "client", "bill to"],
			"hi": ["ग्राहक", "खरीदार"],
			"ar": ["العميل", "المشتري"],
			"ch": ["客户", "买方"],
			"fr": ["client", "acheteur"],
			"de": ["kunde"],
			"ja": ["顧客"],
			"ko": ["고객"],
			"es": ["cliente"],
			"pt": ["cliente"],
		},
		"transaction_date": {
			"en": ["order date", "so date", "dated"],
			"hi": ["आदेश दिनांक"],
			"ar": ["تاريخ الأمر"],
			"ch": ["订单日期"],
			"fr": ["date de commande"],
			"de": ["bestelldatum"],
			"ja": ["発注日"],
			"ko": ["주문 일자"],
			"es": ["fecha de pedido"],
			"pt": ["data do pedido"],
		},
		"delivery_date": {
			"en": ["delivery date", "ship date", "expected date"],
			"hi": ["वितरण तिथि"],
			"ar": ["تاريخ التسليم"],
			"ch": ["交货日期"],
			"fr": ["date de livraison"],
			"de": ["lieferdatum"],
			"ja": ["納品日"],
			"ko": ["배송 일자"],
			"es": ["fecha de entrega"],
			"pt": ["data de entrega"],
		},
	},
	"Quotation": {
		"party_name": {
			"en": ["customer", "buyer", "client", "quote to"],
			"hi": ["ग्राहक", "उद्धरण के लिए"],
			"ar": ["العميل", "اسم العميل"],
			"ch": ["客户", "报价对象"],
			"fr": ["client", "destinataire du devis"],
			"de": ["kunde", "angebot an"],
			"ja": ["顧客", "見積先"],
			"ko": ["고객", "견적 대상"],
			"es": ["cliente"],
			"pt": ["cliente"],
		},
		"transaction_date": {
			"en": ["quotation date", "quote date", "dated"],
			"hi": ["उद्धरण दिनांक"],
			"ar": ["تاريخ عرض السعر"],
			"ch": ["报价日期"],
			"fr": ["date du devis"],
			"de": ["angebotsdatum"],
			"ja": ["見積日"],
			"ko": ["견적 일자"],
			"es": ["fecha de cotización"],
			"pt": ["data da cotação"],
		},
		"valid_till": {
			"en": ["valid till", "validity", "expiry date", "valid until"],
			"hi": ["वैध तिथि", "मान्यता तक"],
			"ar": ["صالح حتى", "تاريخ الانتهاء"],
			"ch": ["有效期至", "失效日期"],
			"fr": ["valable jusqu'au", "validité"],
			"de": ["gültig bis"],
			"ja": ["有効期限"],
			"ko": ["유효 기간"],
			"es": ["válido hasta"],
			"pt": ["válido até"],
		},
	},
	"Payment Entry": {
		"party": {
			"en": ["party", "customer", "supplier", "vendor", "paid to", "received from"],
			"hi": ["पार्टी", "भुगतान प्राप्तकर्ता"],
			"ar": ["الطرف", "المدفوع له", "المستلم من"],
			"ch": ["对方", "收款方", "付款方"],
			"fr": ["tiers", "payé à", "reçu de"],
			"de": ["partei", "gezahlt an", "erhalten von"],
			"ja": ["相手先", "支払先", "受取人"],
			"ko": ["거래처", "지급 대상", "수취인"],
			"es": ["parte", "pagado a", "recibido de"],
			"pt": ["parte", "pago a", "recebido de"],
		},
		"posting_date": {
			"en": ["payment date", "dated"],
			"hi": ["भुगतान दिनांक"],
			"ar": ["تاريخ الدفع"],
			"ch": ["付款日期"],
			"fr": ["date de paiement"],
			"de": ["zahlungsdatum"],
			"ja": ["支払日"],
			"ko": ["지급 일자"],
			"es": ["fecha de pago"],
			"pt": ["data do pagamento"],
		},
		"paid_amount": {
			"en": ["paid amount", "payment amount"],
			"hi": ["भुगतान राशि"],
			"ar": ["المبلغ المدفوع"],
			"ch": ["付款金额", "已付金额"],
			"fr": ["montant payé"],
			"de": ["gezahlter betrag"],
			"ja": ["支払金額"],
			"ko": ["지급 금액"],
			"es": ["importe pagado"],
			"pt": ["valor pago"],
		},
		"reference_no": {
			"en": ["ref no", "cheque no", "check no", "utr"],
			"hi": ["संदर्भ संख्या", "चेक संख्या"],
			"ar": ["رقم المرجع", "رقم الشيك"],
			"ch": ["参考号", "支票号"],
			"fr": ["référence", "n° de chèque"],
			"de": ["referenz-nr", "scheck-nr"],
			"ja": ["参照番号", "小切手番号"],
			"ko": ["참조 번호", "수표 번호"],
			"es": ["referencia", "n° de cheque"],
			"pt": ["referência", "nº do cheque"],
		},
	},
}


# ---------------------------------------------------------------------------
# Public helpers — used by the rule mapper and the OCR engine.
# ---------------------------------------------------------------------------


def merge_keywords_for_languages(
	target_doctype: str,
	languages: Iterable[str],
	*,
	english_fallback: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
	"""Return a flat ``{fieldname: [aliases...]}`` for *target_doctype*.

	The returned dict merges the multilingual aliases for every language
	in *languages*.  When the DocType isn't in
	:data:`FIELD_KEYWORDS_MULTILINGUAL`, *english_fallback* (typically
	``FieldMapper.FIELD_KEYWORDS[doctype]``) is returned unchanged so the
	rule mapper degrades gracefully.

	Aliases are lower-cased and de-duplicated while preserving order so
	the mapper's "exact match wins" heuristic still picks the same
	English keyword first when the document is in English.
	"""

	# Always include English so we never lose the rule mapper's existing
	# vocabulary when the user picks, say, ``["hi"]``.
	requested = [normalize_language(lang) for lang in languages]
	# Preserve order, drop duplicates.
	seen: set[str] = set()
	ordered: list[str] = []
	for lang in ["en", *requested]:
		if lang in seen:
			continue
		seen.add(lang)
		ordered.append(lang)

	per_doctype = FIELD_KEYWORDS_MULTILINGUAL.get(target_doctype)
	if not per_doctype:
		# Unknown DocType — return the rule mapper's existing keywords
		# verbatim (or an empty dict, but never None).
		return {fn: list(kws) for fn, kws in (english_fallback or {}).items()}

	merged: dict[str, list[str]] = {}
	for fieldname, lang_map in per_doctype.items():
		bag: list[str] = []
		seen_aliases: set[str] = set()
		for lang in ordered:
			for alias in lang_map.get(lang, []) or []:
				low = alias.strip().lower()
				if low and low not in seen_aliases:
					seen_aliases.add(low)
					bag.append(low)
		if bag:
			merged[fieldname] = bag

	# Add any rule-mapper-only fields that we don't have multilingual
	# coverage for yet.  This keeps `mode_of_payment`, `cheque_date`, etc.
	# working even before we expand the dictionary.
	if english_fallback:
		for fn, kws in english_fallback.items():
			if fn in merged:
				continue
			merged[fn] = [k.strip().lower() for k in kws if k]

	return merged


__all__ = [
	"FIELD_KEYWORDS_MULTILINGUAL",
	"SUPPORTED_LANGUAGES",
	"is_supported_language",
	"merge_keywords_for_languages",
	"normalize_language",
]
