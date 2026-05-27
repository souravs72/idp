<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
	<FrappeUIProvider>
		<div class="h-full bg-surface-white">
			<router-view />
			<ConfirmDialog />
		</div>
	</FrappeUIProvider>
</template>

<script setup>
import { FrappeUIProvider, useTheme } from "frappe-ui";
import ConfirmDialog from "./components/ConfirmDialog.vue";

const { initializeTheme } = useTheme();
initializeTheme();
</script>
