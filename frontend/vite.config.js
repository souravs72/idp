// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(async ({ mode }) => {
  const isDev = mode === 'development'

  const config = {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    optimizeDeps: {
      include: ['vue', 'vue-router', 'frappe-ui'],
    },
    server: {
      fs: {
        allow: [path.resolve(__dirname, '..')],
      },
    },
  }

  const frappeui = await importFrappeUIPlugin(isDev, config)
  config.plugins.unshift(
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        indexHtmlPath: '../idp/www/idp.html',
        emptyOutDir: true,
      },
    }),
  )

  return config
})

async function importFrappeUIPlugin(isDev, config) {
  if (isDev) {
    try {
      const fs = await import('node:fs')
      const localVitePluginPath = path.resolve(__dirname, '../frappe-ui/vite')
      if (fs.existsSync(localVitePluginPath)) {
        const module = await import('../frappe-ui/vite')
        console.info('Local frappe-ui vite plugin found, using local plugin')
        config.resolve.alias = {
          ...config.resolve.alias,
          'frappe-ui/tailwind': path.resolve(
            __dirname,
            '../frappe-ui/tailwind/preset.js',
          ),
          'frappe-ui/style.css': path.resolve(
            __dirname,
            '../frappe-ui/src/style.css',
          ),
          'frappe-ui/frappe': path.resolve(
            __dirname,
            '../frappe-ui/frappe/index.js',
          ),
          'frappe-ui': path.resolve(__dirname, '../frappe-ui/src/index.ts'),
        }
        return module.default
      }
    } catch (error) {
      console.warn(
        'Local frappe-ui not found, falling back to npm package:',
        error.message,
      )
    }
  }
  const module = await import('frappe-ui/vite')
  return module.default
}
