// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/chat',
    name: 'ChatHome',
    component: () => import('@/pages/ChatView.vue'),
  },
  {
    path: '/chat/:id',
    name: 'ChatConversation',
    component: () => import('@/pages/ChatView.vue'),
    props: true,
  },
]

const router = createRouter({
  history: createWebHistory('/idp/'),
  routes,
})

export default router
