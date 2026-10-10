// 构建后修复 Vite 在 Windows 上 index.html 脚本引用不正确的问题
import { readFileSync, writeFileSync, readdirSync, statSync } from 'fs'
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
const scriptMatch = html.match(/src="\/assets\/index-[^"\s]+/)
if (scriptMatch) {
  const newSrc = `/assets/${mainJs}?v=${Date.now()}`
  html = html.replace(scriptMatch[0], `src="${newSrc}`)
  writeFileSync(htmlPath, html, 'utf-8')
  console.log(`[fix-index] index.html 已更新: ${mainJs}`)
} else {
  console.log('[fix-index] index.html 无需更新')
}
