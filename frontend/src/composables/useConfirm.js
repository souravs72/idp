// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { reactive } from "vue";

// Singleton dialog state — read by <ConfirmDialog/> mounted in App.vue
// and mutated by confirm()/resolveConfirm() below.
const state = reactive({
	open: false,
	title: "Confirm",
	message: "",
	okLabel: "OK",
	cancelLabel: "Cancel",
	variant: "primary", // "primary" | "danger"
	allowHtml: false,
	_resolve: null,
});

export function useConfirmState() {
	return state;
}

/**
 * Imperative confirm() — returns a Promise<boolean>.
 * Falls back to the native window.confirm only when the SPA root has
 * not mounted <ConfirmDialog/> yet (defensive guard for SSR / tests).
 */
export function confirm(message, opts = {}) {
	if (typeof window === "undefined" || !state) {
		return Promise.resolve(window?.confirm(stripHtml(message)) ?? false);
	}
	state.message = message;
	state.title = opts.title || "Confirm";
	state.okLabel = opts.okLabel || "OK";
	state.cancelLabel = opts.cancelLabel || "Cancel";
	state.variant = opts.variant || "primary";
	state.allowHtml = !!opts.allowHtml;
	return new Promise((resolve) => {
		state._resolve = resolve;
		state.open = true;
	});
}

export function resolveConfirm(value) {
	const r = state._resolve;
	state._resolve = null;
	state.open = false;
	if (r) r(value);
}

function stripHtml(s) {
	return String(s || "")
		.replace(/<br\s*\/?>/gi, "\n")
		.replace(/<[^>]+>/g, "");
}
