// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  FrappeUI,
  Button,
  Input,
  FormControl,
  ErrorMessage,
  Dialog,
  Alert,
  Badge,
  setConfig,
  frappeRequest,
} from 'frappe-ui'

import App from './App.vue'
import router from './router'

let app = createApp(App)

setConfig('resourceFetcher', frappeRequest)
app.use(FrappeUI)
app.use(createPinia())
app.use(router)

// Register common components globally
const globalComponents = {
  Button,
  Input,
  FormControl,
  ErrorMessage,
  Dialog,
  Alert,
  Badge,
}
for (let key in globalComponents) {
  app.component(key, globalComponents[key])
}

if (import.meta.env.DEV) {
  frappeRequest({ url: '/api/method/idp.www.idp.get_context_for_dev' }).then(
    (values) => {
      for (let key in values) {
        window[key] = values[key]
      }
      app.mount('#app')
    },
  )
} else {
  app.mount('#app')
}
