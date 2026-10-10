// 构建前清理 static/ 目录，确保干净构建
import { readdirSync, statSync, unlinkSync, rmdirSync } from 'fs'
import { join } from 'path'

const staticDir = join(process.cwd(), '..', 'static')

function removeRecursively(dir) {
  const entries = readdirSync(dir, { withFileTypes: true })
  for (const entry of entries) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      removeRecursively(path)
      rmdirSync(path)
    } else {
      unlinkSync(path)
    }
  }
}

try {
  const stats = statSync(staticDir)
  if (stats.isDirectory()) {
    removeRecursively(staticDir)
    console.log('[clean-static] static/ 已清空')
  }
} catch {
  console.log('[clean-static] static/ 不存在，跳过')
}
