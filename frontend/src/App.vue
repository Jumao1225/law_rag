<template>
  <div class="app-container">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>智能法律助手</h2>
        <button class="new-chat-btn" @click="createNewSession">⊕ 新建会话</button>
      </div>

      <div class="upload-section">
        <label class="upload-btn">
          上传知识库文件
          <input type="file" accept=".txt,.pdf" @change="uploadFile" style="display: none;" />
        </label>
        <div v-if="uploadStatus" class="upload-status-wrapper">
          <div class="status-text">{{ uploadStatus }}</div>
          <div class="progress-bar-container" v-if="uploadProgress > 0 && uploadProgress < 100">
            <div class="progress-bar-fill" :style="{ width: uploadProgress + '%' }"></div>
          </div>
        </div>
        
        <div class="kb-files-list" v-if="kbFiles.length > 0">
          <div class="kb-files-header">📚 已上传文档 ({{ kbFiles.length }})</div>
          <div v-for="f in kbFiles" :key="f" class="kb-file-item" :title="f">
            <span class="kb-file-name">📄 {{ f }}</span>
            <button class="kb-file-delete" @click="deleteKbFile(f)" title="删除文档">✕</button>
          </div>
        </div>
      </div>

      <div class="history-list">
        <div class="history-header">🕘 历史会话</div>
        <div 
          v-for="session in sessions" 
          :key="session.session_id"
          class="session-item"
          :class="{ active: currentSessionId === session.session_id }"
          @click="selectSession(session.session_id)"
        >
          <div class="session-info">
            <span v-if="session.pinned">📌</span>
            <span class="session-label">{{ session.label }}</span>
          </div>
          <div class="session-actions">
            <button @click.stop="togglePin(session.session_id)" class="action-btn">
              {{ session.pinned ? '取消' : '置顶' }}
            </button>
            <button @click.stop="deleteSession(session.session_id)" class="action-btn danger">
              删除
            </button>
          </div>
        </div>
      </div>
    </aside>

    <main class="chat-main">
      <div class="chat-messages" ref="messagesContainer">
        <div 
          v-for="(msg, index) in messages" 
          :key="index"
          class="message-row"
          :class="msg.role === 'user' ? 'row-user' : 'row-assistant'"
        >
          <div class="message-bubble" :class="`bubble-${msg.role}`">
            <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
            <div v-else>{{ msg.content }}</div>
          </div>
        </div>
        <div v-if="isTyping" class="message-row row-assistant">
          <div class="message-bubble bubble-assistant typing-indicator">
            思考中...
          </div>
        </div>
      </div>

      <div class="chat-input-container">
        <textarea 
          v-model="inputMessage" 
          @keydown.enter.prevent="sendMessage"
          placeholder="请输入你的法律问题..."
          rows="1"
        ></textarea>
        <button class="send-btn" @click="sendMessage" :disabled="isTyping || !inputMessage.trim()">
          发送
        </button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { marked } from 'marked'

const API_BASE = 'http://localhost:8000/api'

const sessions = ref([])
const currentSessionId = ref('')
const messages = ref([])
const inputMessage = ref('')
const isTyping = ref(false)
const uploadStatus = ref('')
const uploadProgress = ref(0)
const messagesContainer = ref(null)
const kbFiles = ref([])

const fetchKbFiles = async () => {
  try {
    const res = await fetch(`${API_BASE}/knowledge-base/files`)
    const data = await res.json()
    if (data.status === 'success') {
      kbFiles.value = data.files
    }
  } catch (error) {
    console.error("Failed to fetch KB files", error)
  }
}

const renderMarkdown = (text) => {
  return marked(text || '')
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const fetchSessions = async () => {
  try {
    const res = await fetch(`${API_BASE}/sessions`)
    sessions.value = await res.json()
    if (!currentSessionId.value && sessions.value.length > 0) {
      selectSession(sessions.value[0].session_id)
    } else if (sessions.value.length === 0) {
      createNewSession()
    }
  } catch (error) {
    console.error("Failed to fetch sessions", error)
  }
}

const selectSession = async (id) => {
  currentSessionId.value = id
  messages.value = []
  try {
    const res = await fetch(`${API_BASE}/sessions/${id}/messages`)
    messages.value = await res.json()
    scrollToBottom()
  } catch (error) {
    console.error("Failed to fetch messages", error)
  }
}

const createNewSession = async () => {
  try {
    const res = await fetch(`${API_BASE}/sessions`, { method: 'POST' })
    const data = await res.json()
    currentSessionId.value = data.session_id
    messages.value = [{ role: 'assistant', content: '你好，我是一个法律问答助手，我有什么可以帮助你？' }]
    await fetchSessions()
    scrollToBottom()
  } catch (error) {
    console.error("Failed to create session", error)
  }
}

const deleteSession = async (id) => {
  try {
    await fetch(`${API_BASE}/sessions/${id}`, { method: 'DELETE' })
    if (currentSessionId.value === id) {
      currentSessionId.value = ''
    }
    await fetchSessions()
  } catch (error) {
    console.error("Failed to delete session", error)
  }
}

const togglePin = async (id) => {
  try {
    await fetch(`${API_BASE}/sessions/${id}/pin`, { method: 'POST' })
    await fetchSessions()
  } catch (error) {
    console.error("Failed to pin session", error)
  }
}

const uploadFile = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  
  const formData = new FormData()
  formData.append('file', file)
  
  uploadStatus.value = '上传中并处理知识库...'
  uploadProgress.value = 0
  
  let progressInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/upload/progress/${encodeURIComponent(file.name)}`)
      const data = await res.json()
      if (data.progress >= 0) {
        uploadProgress.value = data.progress
        if (data.status) uploadStatus.value = data.status
      }
    } catch (e) {
      console.error('Progress fetch error:', e)
    }
  }, 1000)

  try {
    const res = await fetch(`${API_BASE}/upload`, {
      method: 'POST',
      body: formData
    })
    clearInterval(progressInterval)
    const data = await res.json()
    if (data.status === 'success') {
      uploadProgress.value = 100
      uploadStatus.value = '✅ 上传并入库成功'
      await fetchKbFiles()
    } else {
      uploadProgress.value = 0
      uploadStatus.value = '❌ 上传失败'
    }
  } catch (error) {
    clearInterval(progressInterval)
    uploadProgress.value = 0
    uploadStatus.value = '❌ 上传发生错误'
    console.error(error)
  }
  
  setTimeout(() => {
    uploadStatus.value = ''
    uploadProgress.value = 0
  }, 4000)
}

const deleteKbFile = async (filename) => {
  if (!confirm(`确定要删除文档「${filename}」吗？此操作将从知识库中移除该文档的所有内容。`)) return
  try {
    const res = await fetch(`${API_BASE}/knowledge-base/files/${encodeURIComponent(filename)}`, { method: 'DELETE' })
    const data = await res.json()
    if (data.status === 'success') {
      uploadStatus.value = `✅ ${data.message}`
      await fetchKbFiles()
    } else {
      uploadStatus.value = '❌ 删除失败'
    }
  } catch (error) {
    uploadStatus.value = '❌ 删除发生错误'
    console.error(error)
  }
  setTimeout(() => uploadStatus.value = '', 3000)
}

const sendMessage = async () => {
  const msg = inputMessage.value.trim()
  if (!msg || isTyping.value) return
  
  if (!currentSessionId.value) {
    await createNewSession()
  }

  messages.value.push({ role: 'user', content: msg })
  inputMessage.value = ''
  isTyping.value = true
  scrollToBottom()

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        session_id: currentSessionId.value,
        message: msg
      })
    })

    if (!response.body) throw new Error("No response body")
    
    // Create assistant message placeholder
    const assistantMsg = { role: 'assistant', content: '' }
    messages.value.push(assistantMsg)
    
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      assistantMsg.content += decoder.decode(value, { stream: true })
      scrollToBottom()
    }
    isTyping.value = false
    await fetchSessions() // refresh titles
  } catch (error) {
    console.error("Chat error", error)
    messages.value.push({ role: 'assistant', content: '\n\n**请求出错，请重试。**' })
    isTyping.value = false
  }
}

onMounted(() => {
  fetchSessions()
  fetchKbFiles()
})
</script>

<style>
/* Modern Resets & Variables */
:root {
  --primary: #3b82f6;
  --primary-hover: #2563eb;
  --bg-color: #f8fafc;
  --sidebar-bg: #ffffff;
  --border-color: #e2e8f0;
  --text-main: #1e293b;
  --text-muted: #64748b;
  --user-bubble: #eff6ff;
  --user-text: #1e3a8a;
  --assistant-bubble: #ffffff;
  --danger: #ef4444;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background-color: var(--bg-color);
  color: var(--text-main);
  height: 100vh;
  overflow: hidden;
}

.app-container {
  display: flex;
  height: 100vh;
}

/* Sidebar */
.sidebar {
  width: 300px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 10px rgba(0,0,0,0.02);
}

.sidebar-header {
  padding: 1.5rem 1rem;
  border-bottom: 1px solid var(--border-color);
}

.sidebar-header h2 {
  margin: 0 0 1rem 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--primary);
}

.new-chat-btn {
  width: 100%;
  padding: 0.75rem;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.new-chat-btn:hover {
  background: var(--primary-hover);
}

.upload-section {
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
}

.upload-btn {
  display: block;
  text-align: center;
  padding: 0.75rem;
  background: #f1f5f9;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.9rem;
  transition: all 0.2s;
}

.upload-btn:hover {
  background: #e2e8f0;
  color: var(--text-main);
}

.upload-status-wrapper {
  margin-top: 0.5rem;
  text-align: center;
}

.status-text {
  font-size: 0.8rem;
  color: var(--primary);
  margin-bottom: 4px;
}

.progress-bar-container {
  width: 100%;
  height: 6px;
  background-color: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  margin-top: 6px;
}

.progress-bar-fill {
  height: 100%;
  background-color: var(--primary);
  transition: width 0.5s ease;
}

.kb-files-list {
  margin-top: 1rem;
  max-height: 150px;
  overflow-y: auto;
}

.kb-files-header {
  font-size: 0.8rem;
  color: var(--text-muted);
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.kb-file-item {
  font-size: 0.8rem;
  color: var(--text-main);
  padding: 0.3rem 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
}

.kb-file-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.kb-file-delete {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0.15rem 0.3rem;
  border-radius: 4px;
  opacity: 0;
  transition: all 0.2s;
  flex-shrink: 0;
}

.kb-file-item:hover .kb-file-delete {
  opacity: 1;
}

.kb-file-delete:hover {
  color: var(--danger);
  background: #fef2f2;
}

/* History List */
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.history-header {
  font-size: 0.85rem;
  color: var(--text-muted);
  font-weight: 600;
  margin-bottom: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.session-item {
  padding: 0.75rem;
  border-radius: 8px;
  margin-bottom: 0.5rem;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.2s;
}

.session-item:hover {
  background: #f1f5f9;
}

.session-item.active {
  background: #e0f2fe;
}

.session-info {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.9rem;
  flex: 1;
}

.session-actions {
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.session-item:hover .session-actions {
  opacity: 1;
}

.action-btn {
  background: none;
  border: none;
  font-size: 0.75rem;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0.2rem;
}

.action-btn:hover {
  color: var(--primary);
}

.action-btn.danger:hover {
  color: var(--danger);
}

/* Chat Main */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-color);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
  scroll-behavior: smooth;
}

.message-row {
  display: flex;
  margin-bottom: 1.5rem;
}

.row-user {
  justify-content: flex-end;
}

.row-assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: 75%;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  font-size: 0.95rem;
  line-height: 1.6;
  box-shadow: 0 2px 5px rgba(0,0,0,0.03);
}

.bubble-user {
  background: var(--user-bubble);
  color: var(--user-text);
  border-bottom-right-radius: 4px;
}

.bubble-assistant {
  background: var(--assistant-bubble);
  border: 1px solid var(--border-color);
  border-bottom-left-radius: 4px;
}

/* Markdown Styles inside bubble */
.bubble-assistant p { margin-top: 0; }
.bubble-assistant p:last-child { margin-bottom: 0; }
.bubble-assistant pre {
  background: #f1f5f9;
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
}
.bubble-assistant code {
  background: #f1f5f9;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: monospace;
}
.bubble-assistant pre code {
  background: none;
  padding: 0;
}
.bubble-assistant table {
  border-collapse: collapse;
  width: 100%;
}
.bubble-assistant th, .bubble-assistant td {
  border: 1px solid var(--border-color);
  padding: 0.5rem;
}

.typing-indicator {
  color: var(--text-muted);
  font-style: italic;
  padding: 0.75rem 1.25rem;
}

/* Input Area */
.chat-input-container {
  padding: 1.5rem;
  background: var(--sidebar-bg);
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 1rem;
  align-items: center;
}

textarea {
  flex: 1;
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  resize: none;
  font-family: inherit;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.2s;
}

textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.send-btn {
  background: var(--primary);
  color: white;
  border: none;
  padding: 1rem 1.5rem;
  border-radius: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--primary-hover);
}

.send-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

/* Responsive */
@media (max-width: 768px) {
  .app-container {
    flex-direction: column;
  }
  .sidebar {
    width: 100%;
    height: 30vh;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }
  .chat-main {
    height: 70vh;
  }
}
</style>
