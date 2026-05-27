<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
	<Dialog :options="{ title: state.title, size: 'sm' }" v-model="open">
		<template #body-content>
			<div class="space-y-4">
				<p
					v-if="state.allowHtml"
					class="text-sm text-gray-700 dark:text-gray-300"
					v-html="state.message"
				/>
				<p v-else class="text-sm whitespace-pre-line text-gray-700 dark:text-gray-300">
					{{ state.message }}
				</p>
				<div class="flex items-center justify-end gap-3 pt-2">
					<button
						class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
						@click="resolveConfirm(false)"
					>
						{{ state.cancelLabel }}
					</button>
					<button :class="okBtnClass" @click="resolveConfirm(true)">
						{{ state.okLabel }}
					</button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed } from "vue";
import { Dialog } from "frappe-ui";
import { useConfirmState, resolveConfirm } from "../composables/useConfirm";

const state = useConfirmState();

// Treat closing the dialog (esc, backdrop, X) as "cancel".
const open = computed({
	get: () => state.open,
	set: (v) => {
		if (!v) resolveConfirm(false);
	},
});

const okBtnClass = computed(() => {
	if (state.variant === "danger") {
		return "rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700";
	}
	return "rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700";
});
</script>
