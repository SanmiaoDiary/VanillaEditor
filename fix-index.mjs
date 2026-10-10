// 修复 Vite 在 Windows 上构建后 index.html 脚本引用不正确的问题
import { readFileSync, writeFileSync, readdirSync, statSync, unlinkSync } from 'fs'
import { join } from 'path'

const staticDir = join(process.cwd(), '..', 'static')
const assetsDir = join(staticDir, 'assets')

function findMainJs() {
  const files = readdirSync(assetsDir)
  const candidates = files
    .filter(f => f.startsWith('index-') && f.endsWith('.js') && !f.endsWith('.map'))
    .sort((a, b) => statSync(join(assetsDir, a)).size - statSync(join(assetsDir, b)).size)
  return candidates[0] || null
}

const mainJs = findMainJs()
if (!mainJs) {
  console.error('[fix-index] 未找到 index-*.js，跳过')
  process.exit(0)
}

const htmlPath = join(staticDir, 'index.html')
let html = readFileSync(htmlPath, 'utf-8')

// 替换脚本引用，并加 ?v= 防止浏览器缓存
html = html.replace(/src="\/assets\/index-[^?"]+(?:\?[^"]*)?"/, (match) => {
  const base = match.match(/src="([^"]+)"/)[1]
  return `src="${base}?v=${Date.now()}"`
})

writeFileSync(htmlPath, html, 'utf-8')
console.log(`[fix-index] index.html 已更新: ${mainJs}`)

// 清理旧的 index-*.js 文件（保留最新的一个）
const indexFiles = readdirSync(assetsDir)
  .filter(f => f.startsWith('index-') && f.endsWith('.js') && !f.endsWith('.map'))
  .sort((a, b) => statSync(join(assetsDir, a)).mtimeMs - statSync(join(assetsDir, b)).mtimeMs)
for (const f of indexFiles.slice(0, -1)) {
  unlinkSync(join(assetsDir, f))
  console.log(`[fix-index] 已删除旧 chunk: ${f}`)
}


