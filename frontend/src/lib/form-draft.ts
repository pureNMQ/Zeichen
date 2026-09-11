// 表单草稿暂存(REQ ff7a0aa2):创建对话框关闭/误关后可恢复上次未提交内容。
// 草稿按 项目×表单 存 localStorage;读写失败静默降级为无草稿。

export function readDraft<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

export function writeDraft(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 存储不可用时放弃暂存,不影响表单本身
  }
}

export function clearDraft(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // 同上
  }
}
