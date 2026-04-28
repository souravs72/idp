// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'DocumentUpload',
    component: () => import('@/pages/DocumentUpload.vue'),
  },
  {
    path: '/review',
    name: 'ExtractionReview',
    component: () => import('@/pages/ExtractionReview.vue'),
  },
  {
    path: '/compare',
    name: 'ComparisonView',
    component: () => import('@/pages/ComparisonView.vue'),
  },
  {
    path: '/history',
    name: 'ProcessingHistory',
    component: () => import('@/pages/ProcessingHistory.vue'),
  },
  {
    path: '/bank-statement',
    name: 'BankStatementView',
    component: () => import('@/pages/BankStatementView.vue'),
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
