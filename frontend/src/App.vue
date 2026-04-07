<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <FrappeUIProvider>
    <div class="h-full bg-surface-white">
      <router-view />
    </div>
  </FrappeUIProvider>
</template>

<script setup>
import { FrappeUIProvider, useTheme } from 'frappe-ui'

const { initializeTheme } = useTheme()
initializeTheme()
</script>
