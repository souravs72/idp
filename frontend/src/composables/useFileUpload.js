// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { ref, computed } from 'vue'
import { uploadDocument } from '@/utils/api'
import { useSettings } from './useSettings'

/**
 * Composable for file upload state and drag-drop logic.
 */
export function useFileUpload() {
  const file = ref(null)
  const fileUrl = ref('')
  const fileName = ref('')
  const mimeType = ref('')
  const fileSize = ref(0)
  const uploading = ref(false)
  const uploadError = ref(null)
  const isDragging = ref(false)

  const { settings } = useSettings()

  const hasFile = computed(() => !!file.value)

  function validateFile(f) {
    const maxSize = (settings.value?.max_file_size_mb || 25) * 1024 * 1024
    if (f.size > maxSize) {
      return `File too large (${(f.size / 1024 / 1024).toFixed(1)} MB). Maximum: ${settings.value?.max_file_size_mb || 25} MB.`
    }

    const supportedMimes = settings.value?.supported_mime_types || []
    if (supportedMimes.length > 0 && !supportedMimes.includes(f.type)) {
      const exts = settings.value?.supported_formats?.join(', ') || ''
      return `Unsupported file type: ${f.type}. Supported: ${exts}`
    }

    return null
  }

  function selectFile(f) {
    const validationError = validateFile(f)
    if (validationError) {
      uploadError.value = validationError
      return false
    }
    file.value = f
    fileName.value = f.name
    mimeType.value = f.type
    fileSize.value = f.size
    uploadError.value = null
    return true
  }

  async function upload() {
    if (!file.value) {
      uploadError.value = 'No file selected'
      return null
    }

    uploading.value = true
    uploadError.value = null

    try {
      const response = await uploadDocument(file.value)
      const result = response.message || response
      if (result.success) {
        fileUrl.value = result.file_url
        return result
      } else {
        uploadError.value = result.error || 'Upload failed'
        return null
      }
    } catch (err) {
      uploadError.value = err.message || 'Upload failed'
      return null
    } finally {
      uploading.value = false
    }
  }

  function reset() {
    file.value = null
    fileUrl.value = ''
    fileName.value = ''
    mimeType.value = ''
    fileSize.value = 0
    uploadError.value = null
    isDragging.value = false
  }

  function onDragEnter(e) {
    e.preventDefault()
    isDragging.value = true
  }

  function onDragLeave(e) {
    e.preventDefault()
    isDragging.value = false
  }

  function onDragOver(e) {
    e.preventDefault()
  }

  function onDrop(e) {
    e.preventDefault()
    isDragging.value = false
    const files = e.dataTransfer?.files
    if (files && files.length > 0) {
      selectFile(files[0])
    }
  }

  return {
    file,
    fileUrl,
    fileName,
    mimeType,
    fileSize,
    uploading,
    uploadError,
    isDragging,
    hasFile,
    validateFile,
    selectFile,
    upload,
    reset,
    onDragEnter,
    onDragLeave,
    onDragOver,
    onDrop,
  }
}
