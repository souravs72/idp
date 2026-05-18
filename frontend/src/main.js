// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { initSocket } from './socket'
import router from './router'
import App from './App.vue'

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


let app = createApp(App)

setConfig('resourceFetcher', frappeRequest)
// Disable frappe-ui's bundled socket bootstrap — it hard-codes port
// 9000 and ignores ``common_site_config.socketio_port``, which causes
// a ``net::ERR_CONNECTION_REFUSED`` storm against ``localhost:9000``
// on benches that publish the realtime worker elsewhere (e.g. 9005).
// Our own ``src/socket.js`` singleton handles the connection.
app.use(FrappeUI, { socketio: false })
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

let socket
if (import.meta.env.DEV) {
  frappeRequest({ url: '/api/method/idp.www.idp.get_context_for_dev' }).then(
    (values) => {
      for (let key in values) {
        window[key] = values[key]
      }
      socket = initSocket()
      app.config.globalProperties.$socket = socket
      app.mount('#app')
    },
  )
} else {
  socket = initSocket()
  app.config.globalProperties.$socket = socket
  app.mount('#app')
}
