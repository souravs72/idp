### Intelligent Document Processing

A Frappe application that extracts structured data from uploaded documents (PDF, images, Excel, CSV, Word) and creates ERPNext records from the extracted data. Built on PaddleOCR for text recognition and rule-based field mapping for ERPNext schema alignment.

### Features

- Multi-format document extraction (PDF, PNG, JPEG, TIFF, WebP, XLSX, XLS, CSV, DOCX)
- OCR via PaddleOCR with 12+ language support
- Rule-based field mapping to ERPNext DocTypes
- Schema and business-rule validation before record creation
- Document comparison and reconciliation against existing records
- Vue 3 SPA frontend with Frappe UI

### Requirements

| Dependency | Version |
|------------|---------|
| Python | >= 3.10 |
| Frappe | v16 |
| ERPNext | v16 |

### Installation

Install using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app idp
```

### Project Structure

```
idp/
├── core/               # Foundation: config, constants, exceptions, logging
├── idp/                # Business logic (extractors, mappers, validators)
├── api/                # HTTP API endpoints (@frappe.whitelist)
├── config/             # Frappe desk configuration
├── public/             # Static assets & compiled frontend
├── templates/          # Jinja templates
├── tests/              # Test suite
└── hooks.py            # Frappe app hooks
```


### Code Conventions

- **Python**: Tabs for indentation, 110-character line length, double quotes, type hints
- **JavaScript/Vue**: Vue 3 Composition API (`<script setup>`), Tailwind CSS
- **API pattern**: `@frappe.whitelist()` decorators, Frappe ORM (`frappe.qb` / `frappe.get_all`) for database access -- no raw SQL with string interpolation
- **Error handling**: `try/except` with `frappe.log_error()`

### Dependencies

**Python** (runtime): frappe, openai, anthropic, twilio==8.5.0, python-docx>=1.1, requests (pypdf and openpyxl provided by Frappe)

**Frontend**: vue 3, vue-router, marked, highlight.js, lucide-vue-next, tailwindcss, echarts, socket.io-client

---

## Documentation

| Document | Description |
|----------|-------------|
| [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | High-level architecture and design decisions |
| [PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Detailed file and directory structure |


---


## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create feature branch
3. Commit changes
4. Open pull request

## 📄 License

MIT License - See LICENSE file

## 📞 Support

- **Documentation**: See docs folder
- **Issues**: GitHub Issues
- **Email**: sanjay.kumar001@gmail.com

---

**Built with Claude.AI by Sanjay Kumar for the Frappe/ERPNext Community**

Version: 1.0.0

