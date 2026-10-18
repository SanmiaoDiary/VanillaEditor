// ── Router ───────────────────────────────────────────────────
const Router = {
  routes: {},
  register(path, render) { this.routes[path] = render; },
  render() {
    const hash = location.hash || '#/login';
    const handler = this.routes[hash] || this.routes['#/login'];
    if (handler) handler();
  },
  go(to) { location.hash = to; }
};
window.addEventListener('hashchange', () => Router.render());

// ── Auth state ───────────────────────────────────────────────
const auth = {
  token: localStorage.getItem('ve_token') || '',
  username: localStorage.getItem('ve_username') || '',
  get isLoggedIn() { return !!this.token; },
  login(tok, user) { this.token = tok; this.username = user; localStorage.setItem('ve_token', tok); localStorage.setItem('ve_username', user); },
  logout() { this.token = ''; this.username = ''; localStorage.removeItem('ve_token'); localStorage.removeItem('ve_username'); }
};

// ── Editor state ─────────────────────────────────────────────
const editor = {
  activeDocId: '', activeFilePath: '', content: '', fileSha: '', gitBranch: 'main', unsaved: false
};
let activePanel = 'files';
let sidebarDocs = [];
let workspaces = [];
let expandedDocs = {};
let commitMsg = '';
let remotes = [];
let commits = [];
let isRegister = false;
let loginError = '';
let saveTimer = null;
let fontSize = parseInt(localStorage.getItem('ve_font_size') || '14', 10);
let mobilePreviewMode = localStorage.getItem('ve_mobile_preview') === '1';
let previewVisible = false; // 桌面端预览默认折叠
// 已打开的标签页
let openTabs = [];
let activeTabId = null;
document.documentElement.style.setProperty('--ed-font-size', fontSize + 'px');

// ── API ──────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (auth.token) headers['Authorization'] = 'Bearer ' + auth.token;
  const res = await fetch('/api' + path, { ...opts, headers });
  // 登录/注册接口的 401 表示密码错误，交给调用方展示错误；其他接口 401 视为登录过期
  const isAuthForm = path === '/auth/login' || path === '/auth/init';
  if (res.status === 401 && !isAuthForm) { auth.logout(); Router.go('#/login'); return null; }
  if (!res.ok) {
    let msg = '请求失败（' + res.status + '）';
    try {
      const data = await res.json();
      if (data && data.error) msg = String(data.error);
    } catch (e) {
      if (res.status >= 500) msg = '服务器内部错误（' + res.status + '），请查看后端日志';
    }
    throw new Error(msg);
  }
  return res.json();
}

// ── Toast ────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const map = { ok: 'success', err: 'danger', info: 'info' };
  const el = document.createElement('div');
  el.className = 'toast-container position-fixed bottom-0 end-0 p-3';
  el.innerHTML =
    '<div class="toast align-items-center text-bg-' + (map[type] || 'info') + ' border-0 show" role="alert">' +
      '<div class="d-flex"><div class="toast-body">' + msg + '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>' +
    '</div>';
  document.body.appendChild(el);
  const t = el.querySelector('.toast');
  new bootstrap.Toast(t, { delay: 3000 }).show();
  t.addEventListener('hidden.bs.toast', () => el.remove());
}

// ── Markdown parser ──────────────────────────────────────────
function parseMd(src) {
  if (!src) return '';
  const inline = s => {
    const code = [];
    s = s.replace(/`([^`]+)`/g, (m, c) => { code.push(c); return '\u0000' + (code.length - 1) + '\u0000'; });
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1">');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');
    s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    s = s.replace(/\u0000(\d+)\u0000/g, (m, i) => '<code>' + code[+i] + '</code>');
    return s;
  };
  const renderList = (items, idx, indent) => {
    const tag = items[idx].ordered ? 'ol' : 'ul';
    let html = '<' + tag + '>', i = idx;
    while (i < items.length && items[i].indent >= indent) {
      const it = items[i];
      if (it.indent > indent) {
        const sub = renderList(items, i, it.indent);
        html += sub.html; i = sub.next; continue;
      }
      html += '<li>' + inline(esc(it.text)) + '</li>';
      i++;
    }
    return { html: html + '</' + tag + '>', next: i };
  };

  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  const listRe = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
  const isBlockStart = l =>
    /^\s*$/.test(l) || /^(#{1,6})\s+/.test(l) || /^```/.test(l) || /^\s*>/.test(l) ||
    listRe.test(l) || (/^\s*\|.*\|\s*$/.test(l)) ||
    /^\s*([-*_])\s*(\1\s*){2,}$/.test(l);

  let html = '', i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // 代码块 ```lang ... ```
    const fence = line.match(/^```(\S*)\s*$/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++;
      html += '<pre><code>' + esc(buf.join('\n')) + '</code></pre>';
      continue;
    }

    if (/^\s*$/.test(line)) { i++; continue; }

    // 标题
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { html += '<h' + h[1].length + '>' + inline(esc(h[2])) + '</h' + h[1].length + '>'; i++; continue; }

    // 分割线
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) { html += '<hr>'; i++; continue; }

    // 引用块
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
      html += '<blockquote>' + parseMd(buf.join('\n')) + '</blockquote>';
      continue;
    }

    // 表格
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const cells = r => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
      const head = cells(line);
      i += 2;
      html += '<table><thead><tr>' + head.map(c => '<th>' + inline(esc(c)) + '</th>').join('') + '</tr></thead><tbody>';
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        html += '<tr>' + cells(lines[i]).map(c => '<td>' + inline(esc(c)) + '</td>').join('') + '</tr>';
        i++;
      }
      html += '</tbody></table>';
      continue;
    }

    // 列表（支持 - * + 与数字序号、缩进嵌套）
    const lm = line.match(listRe);
    if (lm) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(listRe);
        if (!m) break;
        items.push({ indent: m[1].length, ordered: /^\d/.test(m[2]), text: m[3] });
        i++;
      }
      html += renderList(items, 0, items[0].indent).html;
      continue;
    }

    // 段落
    const buf = [line];
    i++;
    while (i < lines.length && !isBlockStart(lines[i])) { buf.push(lines[i]); i++; }
    html += '<p>' + inline(esc(buf.join('\n'))).replace(/\n/g, '<br>') + '</p>';
  }
  return html;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Markdown syntax highlighter ──────────────────────────────
// 行内语法着色：把 #、**、*、-、> 等标记字符单独包裹 <span class="hl-mk"> 蓝色高亮，
// ── Markdown syntax highlighter ──────────────────────────────
// 输出 <pre> 内容：每行用 \n 分隔，行内语法标记用 <span> 着色。
// <pre> 与 textarea 共享相同字体/行高/内边距，光标位置天然对齐。
function hlMd(src) {
  if (!src) return '';
  const escH = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const inl = s => {
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (m, c) => { codes.push(c); return '\x00' + codes.length + '\x00'; });
    s = s.replace(/\*\*\*([^*]+)\*\*\*/g, '<span class="hl-b"><span class="hl-b">$1</span></span>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<span class="hl-b">$1</span>');
    s = s.replace(/__([^_]+)__/g, '<span class="hl-b">$1</span>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<span class="hl-i">$2</span>');
    s = s.replace(/(^|[^_])_([^_\n]+)_/g, '$1<span class="hl-i">$2</span>');
    s = s.replace(/~~([^~]+)~~/g, '<span class="hl-d">$1</span>');
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<span class="hl-img">[$1]</span><span class="hl-url">($2)</span>');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<span class="hl-lnk">$1</span><span class="hl-url">($2)</span>');
    s = s.replace(/\x00(\d+)\x00/g, (m, i) => '<code>' + escH(codes[+i]) + '</code>');
    return s;
  };
  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  return lines.map(line => {
    const esc = escH(line);
    // 行首 # 标题标记
    const hm = esc.match(/^(#{1,6}\s)(.*)$/);
    if (hm) return '<span class="hl-mk">' + hm[1] + '</span>' + inl(hm[2]);
    // 行首 > 引用标记
    const bq = esc.match(/^(&gt;\s?)(.*)$/);
    if (bq) return '<span class="hl-mk">' + bq[1] + '</span>' + inl(bq[2]);
    // 行首 - * + 列表或数字. 列表
    const lm = esc.match(/^(\s*[-*+] |\s*\d+\.)\s+(.*)$/);
    if (lm) return '<span class="hl-mk">' + lm[1] + '</span>' + inl(lm[2]);
    return inl(esc);
  }).join('\n');
}

// 渲染高亮层 + 行号
function renderHighlight(content) {
  const hlEl = document.getElementById('veHighlight');
  const lnEl = document.getElementById('veLnNums');
  if (!hlEl || !lnEl) return;
  const lines = (content || '').replace(/\r\n?/g, '\n').split('\n');
  hlEl.innerHTML = hlMd(content);
  const totalLines = Math.max(lines.length, 1);
  let lnHtml = '';
  for (let i = 1; i <= totalLines; i++) lnHtml += i + '\n';
  lnEl.textContent = lnHtml;
}

function togglePreview() {
  previewVisible = !previewVisible;
  if (window.innerWidth < 768) return; // 移动端走 applyMobilePreviewState
  const split = document.querySelector('.ve-split');
  if (!split) return;
  const existing = document.getElementById('vePreview');
  if (previewVisible) {
    // 重建预览 pane 并插入到 resizer 之后
    const pr = document.createElement('div');
    pr.className = 'pane ve-preview';
    pr.id = 'vePreview';
    pr.innerHTML = '<div class="ve-scroll">' + parseMd(editor.content || '') + '</div>';
    const resizer = document.getElementById('veSplitResizer');
    if (resizer) resizer.after(pr);
    else split.appendChild(pr);
  } else {
    // 从 DOM 中移除预览 pane，编辑区自动占满宽度
    if (existing) existing.remove();
  }
  const btn = document.getElementById('vePreviewToggleDesktop');
  if (btn) btn.innerHTML = '<i class="bi bi-' + (previewVisible ? 'eye-slash' : 'eye') + '"></i>';
}

// ── Clock (只更新文本，避免整页重绘) ──────────────────────────
setInterval(() => {
  const c = document.getElementById('veClock');
  if (c) c.textContent = new Date().toLocaleTimeString();
}, 1000);

// ── Login / Register ─────────────────────────────────────────
function renderLogin() {
  document.getElementById('app').innerHTML =
    '<div class="container d-flex align-items-center justify-content-center h-100">' +
      '<div class="card shadow-sm" style="width:100%;max-width:400px">' +
        '<div class="card-body p-4">' +
          '<div class="text-center mb-4">' +
            '<i class="bi bi-journal-richtext" style="font-size:2rem;color:var(--ve-accent)"></i>' +
            '<h4 class="mt-2 mb-1" style="color:var(--ve-accent)">VanillaEditor</h4>' +
            '<p class="text-secondary small mb-0">分布式离线 Markdown 编辑器</p>' +
          '</div>' +
          '<form onsubmit="handleAuth(event)">' +
            '<div class="mb-3">' +
              '<label class="form-label small" for="u">用户名</label>' +
              '<input type="text" class="form-control" id="u" placeholder="用户名" required autofocus>' +
            '</div>' +
            '<div class="mb-3">' +
              '<label class="form-label small" for="p">密码</label>' +
              '<input type="password" class="form-control" id="p" placeholder="密码" required>' +
            '</div>' +
            (isRegister ?
            '<div class="mb-3">' +
              '<label class="form-label small" for="cp">确认密码</label>' +
              '<input type="password" class="form-control" id="cp" placeholder="确认密码">' +
            '</div>' : '') +
            (loginError ? '<div class="alert alert-danger py-2 small" role="alert">' + esc(loginError) + '</div>' : '') +
            '<button type="submit" class="btn btn-primary w-100 mb-2" id="loginBtn">' +
              '<i class="bi ' + (isRegister ? 'bi-person-plus' : 'bi-box-arrow-in-right') + ' me-1"></i>' + (isRegister ? '注册' : '登录') +
            '</button>' +
            '<button type="button" class="btn btn-link w-100 text-secondary" onclick="toggleAuthMode()">' +
              (isRegister ? '已有账号？返回登录' : '还没有账号？点击注册') +
            '</button>' +
          '</form>' +
        '</div>' +
      '</div>' +
    '</div>';
}

function toggleAuthMode() {
  isRegister = !isRegister;
  loginError = '';
  renderLogin();
}

async function handleAuth(e) {
  e.preventDefault();
  const u = document.getElementById('u').value.trim();
  const p = document.getElementById('p').value;
  const cp = document.getElementById('cp');
  loginError = '';
  const btn = document.getElementById('loginBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>处理中...';
  try {
    if (isRegister) {
      if (cp && cp.value !== p) { loginError = '两次输入的密码不一致'; renderLogin(); return; }
      await apiFetch('/auth/init', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    }
    const r = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    if (r) { auth.login(r.token, r.username); Router.go('#/editor'); }
  } catch (err) {
    loginError = err.message || '操作失败';
    renderLogin();
  }
}

// ── File operations ──────────────────────────────────────────
let lastDocsJson = '';

async function loadFiles() {
  const data = await apiFetch('/docs');
  if (!data) return;
  sidebarDocs = data;
  lastDocsJson = JSON.stringify(data);
  if (data.length > 0 && !editor.activeDocId) {
    const first = data[0];
    editor.activeDocId = first.id;
    if (first.children && first.children.length > 0) await openFile(first.id, first.children[0].path);
  }
}

async function loadWorkspaces() {
  try {
    const data = await apiFetch('/workspaces');
    if (data) workspaces = data;
  } catch (e) { workspaces = []; }
}

async function openWorkspace(path) {
  if (!path) return toast('请输入目录路径', 'err');
  const r = await apiFetch('/workspaces', { method: 'POST', body: JSON.stringify({ path }) });
  if (r && r.id) {
    toast('工作区已打开：' + r.name, 'ok');
    await loadWorkspaces();
    renderEditor();
  } else {
    toast('打开失败：' + (r && r.error ? r.error : '未知错误'), 'err');
  }
}

async function closeWorkspace(docId) {
  if (!confirm('关闭工作区「' + docId + '」？（仅删除编辑器内的记录，源文件不会受影响）')) return;
  try {
    await apiFetch('/workspaces/' + encodeURIComponent(docId), { method: 'DELETE' });
    toast('工作区已关闭', 'ok');
    await loadWorkspaces();
    renderEditor();
  } catch (e) { toast('关闭失败：' + e.message, 'err'); }
}

async function scanDirectory(path) {
  if (!path) return [];
  try {
    const r = await apiFetch('/workspaces/scan', { method: 'POST', body: JSON.stringify({ path }) });
    return r && r.files ? r.files : [];
  } catch (e) { return []; }
}

let wsBrowsePath = '';
let wsFileCache = {}; // docId -> files[]
let wsHistory = [];   // path history stack
let wsHistoryIdx = -1;
let wsDefaultRoot = ''; // 默认工作区根目录

async function openWorkspaceModal() {
  const data = await apiFetch('/workspaces');
  if (data) workspaces = data;
  if (!wsDefaultRoot) wsDefaultRoot = '/';
  wsBrowsePath = wsDefaultRoot;
  wsHistory = [wsDefaultRoot];
  wsHistoryIdx = 0;
  const dialogHtml =
    '<div class="mb-3">' +
      '<label class="form-label small text-secondary">服务器路径</label>' +
      '<input class="form-control form-control-sm" id="wsPathInput" value="' + esc(wsBrowsePath) + '">' +
    '</div>' +
    '<div class="d-flex gap-1 mb-3 flex-wrap">' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="wsGoDefault()" title="回到默认工作区"><i class="bi bi-house"></i> 默认</button>' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="wsGoParent()" id="wsBtnParent" title="返回上级"><i class="bi bi-arrow-up"></i> 上级</button>' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="wsGoNext()" id="wsBtnNext" title="下一级"><i class="bi bi-arrow-right"></i> 下级</button>' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="wsGoBack()" id="wsBtnBack" title="上一步"><i class="bi bi-arrow-left"></i> 历史</button>' +
    '</div>' +
    '<div class="border border-secondary-subtle rounded overflow-auto" style="max-height:320px" id="wsDirList"></div>';
  showModal('选择工作区', dialogHtml,
    '<button class="btn btn-sm btn-outline-secondary" onclick="closeModal()">取消</button>' +
    '<button class="btn btn-sm btn-primary" onclick="confirmOpenWorkspace()">打开</button>');
  renderWorkspaceDialog();
}

async function renderWorkspaceDialog() {
  const modalBody = document.getElementById('wsDialogBody');
  const pathDisplay = document.getElementById('wsPathDisplay');
  if (!modalBody) return;
  if (pathDisplay) pathDisplay.value = wsBrowsePath;

  // 加载当前目录内容
  const r = await apiFetch('/fs/children', { method: 'POST', body: JSON.stringify({ path: wsBrowsePath }) });
  const container = document.getElementById('wsDirList');
  if (!container) return;
  if (!r || !r.dirs && !r.files) {
    container.innerHTML = '<div class="text-secondary small p-3">无法读取目录内容</div>';
    return;
  }
  let html = '';
  // 上级目录（非根目录时显示）
  if (wsBrowsePath !== wsDefaultRoot && wsBrowsePath !== '/') {
    html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer text-secondary" onclick="wsGoParent()">' +
      '<i class="bi bi-arrow-return-left me-2"></i>.. 返回上级</div>';
  }
  // 默认工作区根
  html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer text-primary" onclick="wsGoDefault()">' +
    '<i class="bi bi-house me-2"></i>默认工作区</div>';
  // 子目录
  (r.dirs || []).forEach(d => {
    html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer" onclick="wsOpenDir(\'' + esc(d.path) + '\')">' +
      '<i class="bi bi-folder2 me-2 text-warning"></i>' + esc(d.name) + '</div>';
  });
  // 文件（只读，不可选为工作区）
  (r.files || []).slice(0, 50).forEach(f => {
    html += '<div class="ve-ws-item py-1 px-3 border-bottom border-secondary-subtle text-secondary small">' +
      '<i class="bi bi-file-earmark me-2"></i>' + esc(f.name) +
      '<span class="ms-2">' + formatSize(f.size) + '</span></div>';
  });
  if ((r.files || []).length > 50) {
    html += '<div class="px-3 py-2 text-secondary small">… 还有 ' + ((r.files.length || 0) - 50) + ' 个文件</div>';
  }
  container.innerHTML = html || '<div class="text-secondary small p-3">该目录为空</div>';
}

function formatSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function wsGoDefault() { wsNavigateTo(wsDefaultRoot); }
function wsGoParent() {
  if (wsBrowsePath === wsDefaultRoot || wsBrowsePath === '/') return;
  const parts = wsBrowsePath.replace(/\\/g, '/').split('/').filter(Boolean);
  parts.pop();
  wsNavigateTo(parts.length ? parts.join('/') : wsDefaultRoot);
}
function wsGoNext() {
  if (wsHistoryIdx < wsHistory.length - 1) {
    wsHistoryIdx++;
    wsBrowsePath = wsHistory[wsHistoryIdx];
    renderWorkspaceDialog();
  }
}
function wsGoBack() {
  if (wsHistoryIdx > 0) {
    wsHistoryIdx--;
    wsBrowsePath = wsHistory[wsHistoryIdx];
    renderWorkspaceDialog();
  }
}
function wsOpenDir(path) {
  wsNavigateTo(path);
}
function wsNavigateTo(path) {
  path = path.replace(/\\/g, '/');
  if (wsBrowsePath !== path) {
    // 剪掉当前路径之后的历史
    wsHistory = wsHistory.slice(0, wsHistoryIdx + 1);
    wsHistory.push(path);
    wsHistoryIdx = wsHistory.length - 1;
  }
  wsBrowsePath = path;
  renderWorkspaceDialog();
}

async function confirmOpenWorkspace() {
  const pathInput = document.getElementById('wsPathInput');
  const path = pathInput ? pathInput.value.trim() : wsBrowsePath;
  closeModal();
  await openWorkspace(path);
}

async function renderWorkspaceDialog() {
  // 异步加载目录列表，不阻塞按钮状态更新
  const isAtDefault = wsBrowsePath === wsDefaultRoot || wsBrowsePath === '/';
  const canGoParent = !isAtDefault;
  const canGoBack = wsHistoryIdx > 0;
  const canGoNext = wsHistoryIdx < wsHistory.length - 1;

  const inp = document.getElementById('wsPathInput');
  if (inp) inp.value = wsBrowsePath;
  const btnParent = document.getElementById('wsBtnParent');
  if (btnParent) btnParent.disabled = !canGoParent;
  const btnNext = document.getElementById('wsBtnNext');
  if (btnNext) btnNext.disabled = !canGoNext;
  const btnBack = document.getElementById('wsBtnBack');
  if (btnBack) btnBack.disabled = !canGoBack;

  const container = document.getElementById('wsDirList');
  if (!container) return;
  const r = await apiFetch('/fs/children', { method: 'POST', body: JSON.stringify({ path: wsBrowsePath }) });
  if (!r || (!r.dirs && !r.files)) {
    container.innerHTML = '<div class="text-secondary small p-3">无法读取目录内容</div>';
    return;
  }
  let html = '';
  if (!isAtDefault) {
    html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer text-secondary" onclick="wsGoParent()">' +
      '<i class="bi bi-arrow-return-left me-2"></i>.. 返回上级</div>';
  }
  html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer text-primary" onclick="wsGoDefault()">' +
    '<i class="bi bi-house me-2"></i>默认工作区</div>';
  (r.dirs || []).forEach(d => {
    html += '<div class="ve-ws-item py-2 px-3 border-bottom border-secondary-subtle cursor-pointer" onclick="wsOpenDir(\'' + esc(d.path) + '\')">' +
      '<i class="bi bi-folder2 me-2 text-warning"></i>' + esc(d.name) + '</div>';
  });
  (r.files || []).slice(0, 80).forEach(f => {
    html += '<div class="ve-ws-item py-1 px-3 border-bottom border-secondary-subtle text-secondary small">' +
      '<i class="bi bi-file-earmark me-2"></i>' + esc(f.name) +
      '<span class="ms-2">' + formatSize(f.size) + '</span></div>';
  });
  if ((r.files || []).length > 80) {
    html += '<div class="px-3 py-2 text-secondary small">… 还有 ' + ((r.files.length || 0) - 80) + ' 个文件</div>';
  }
  container.innerHTML = html || '<div class="text-secondary small p-3">该目录为空</div>';
}

async function selectWorkspace(docId) {
  editor.activeDocId = docId;
  editor.activeFilePath = '';
  editor.content = '';
  editor.unsaved = false;
  await loadGitData();
  // 缓存工作区文件列表
  if (!wsFileCache[docId]) {
    try {
      wsFileCache[docId] = (await apiFetch('/files/' + docId)) || [];
    } catch (e) { wsFileCache[docId] = []; }
  }
  renderEditor();
}

// 从服务器拉取最新文档列表，有变化时自动刷新侧边栏（其他设备删除/新增也会同步显示）
async function refreshSidebar() {
  if (!auth.isLoggedIn || location.hash !== '#/editor') return;
  let data;
  try { data = await apiFetch('/docs'); } catch (e) { return; }
  if (!data) return;
  const j = JSON.stringify(data);
  if (j === lastDocsJson) {
    // 仅刷新工作区（docs 无变化时仍更新 workspace 列表）
    await loadWorkspaces();
    return;
  }
  sidebarDocs = data;
  lastDocsJson = j;
  // 清空已删除工作区的缓存
  wsFileCache = {};
  for (const ws of workspaces) {
    try { wsFileCache[ws.id] = (await apiFetch('/files/' + ws.id)) || []; } catch (e) {}
  }
  // 当前正在输入或有弹窗打开时不重绘，避免打断操作
  const ae = document.activeElement;
  const typing = ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT');
  const modalOpen = !!document.querySelector('.modal.show');
  const ocOpen = !!document.querySelector('.offcanvas.show');
  if (typing || modalOpen || ocOpen) return;
  // 当前打开的文档/文件若已在服务端被删除，清空编辑区
  if (editor.activeDocId) {
    const doc = data.find(d => d.id === editor.activeDocId);
    if (!doc) {
      editor.activeDocId = ''; editor.activeFilePath = ''; editor.content = ''; editor.unsaved = false;
    } else if (editor.activeFilePath && !(doc.children || []).some(f => f.path === editor.activeFilePath)) {
      editor.activeFilePath = ''; editor.content = ''; editor.unsaved = false;
    }
  }
  renderEditor();
}
setInterval(refreshSidebar, 4000);
window.addEventListener('focus', refreshSidebar);

async function openFile(docId, filePath) {
  editor.activeDocId = docId;
  editor.activeFilePath = filePath;
  const r = await apiFetch('/files/' + docId + '/' + encodeURIComponent(filePath));
  if (r) {
    editor.content = r.content;
    editor.fileSha = r.sha;
    editor.unsaved = false;
  }
  // 将文件加入标签页列表（如已存在则移到最前）
  const tabId = docId + '::' + filePath;
  openTabs = openTabs.filter(t => t.id !== tabId);
  openTabs.unshift({ id: tabId, docId, filePath, label: filePath.split('/').pop(), unsaved: false });
  activeTabId = tabId;
  if (location.hash !== '#/editor') { Router.go('#/editor'); return; }
  renderEditor();
}

function closeTab(tabId) {
  const idx = openTabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;
  const wasActive = tabId === activeTabId;
  openTabs.splice(idx, 1);
  if (wasActive) {
    if (openTabs.length > 0) {
      activeTabId = openTabs[0].id;
      const t = openTabs[0];
      editor.activeDocId = t.docId;
      editor.activeFilePath = t.filePath;
      editor.content = t.content || '';
      editor.unsaved = false;
    } else {
      editor.activeDocId = '';
      editor.activeFilePath = '';
      editor.content = '';
      editor.unsaved = false;
    }
  }
  renderEditor();
}

function switchTab(tabId) {
  if (tabId === activeTabId) return;
  // 切换前先保存当前标签的内容
  const cur = openTabs.find(t => t.id === activeTabId);
  if (cur) cur.content = editor.content;
  const idx = openTabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;
  activeTabId = tabId;
  const t = openTabs[idx];
  editor.activeDocId = t.docId;
  editor.activeFilePath = t.filePath;
  editor.content = t.content || '';
  editor.unsaved = t.unsaved;
  renderEditor();
}

async function createFolder() {
  const name = prompt('新建文件夹名称：');
  if (!name) return;
  const r = await apiFetch('/docs', { method: 'POST', body: JSON.stringify({ name: name, folder: true }) });
  if (r) {
    expandedDocs[r.id] = true;
    await loadFiles();
    renderEditor();
    toast('文件夹已创建', 'ok');
  }
}

async function createFile() {
  const name = prompt('新建文件名称（如 note.md）：');
  if (!name) return;
  if (editor.activeDocId) {
    await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(name), {
      method: 'PUT', body: JSON.stringify({ content: '' })
    });
    await loadFiles();
    await openFile(editor.activeDocId, name);
  } else {
    const r = await apiFetch('/docs', { method: 'POST', body: JSON.stringify({ name: name, content: '' }) });
    if (r) { await loadFiles(); await openFile(r.id, r.name); }
  }
  renderEditor();
}

async function deleteDoc(docId) {
  if (!confirm('确定删除文档「' + docId + '」？其 Git 历史将一并删除。')) return;
  try {
    const r = await apiFetch('/docs/' + encodeURIComponent(docId), { method: 'DELETE' });
    if (!r) return;
  } catch (e) {
    toast('删除失败：' + e.message, 'err');
    return;
  }
  delete expandedDocs[docId];
  // 移除相关标签页
  openTabs = openTabs.filter(t => t.docId !== docId);
  if (editor.activeDocId === docId) {
    editor.activeDocId = ''; editor.activeFilePath = ''; editor.content = ''; editor.unsaved = false;
  }
  await loadFiles();
  renderEditor();
  toast('已删除', 'ok');
}

// ── Git operations ───────────────────────────────────────────
async function loadGitData() {
  if (!editor.activeDocId) return;
  try { const r = await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) }); if (r) remotes = r; } catch (e) {}
  try { const r = await apiFetch('/history/' + editor.activeDocId); if (r) commits = r; } catch (e) {}
  try { const r = await apiFetch('/status/' + editor.activeDocId); if (r && r.branch) editor.gitBranch = r.branch; } catch (e) {}
}

async function pullGit() {
  if (!editor.activeDocId) return toast('请先选择文档', 'err');
  const r = await apiFetch('/sync/pull', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) });
  if (r && r.ok !== false) { await loadGitData(); toast('拉取成功', 'ok'); if (location.hash === '#/editor') renderEditor(); }
  else toast('拉取失败：' + (r && r.error ? r.error : '未知错误'), 'err');
}

async function pushGit() {
  if (!editor.activeDocId) return toast('请先选择文档', 'err');
  const r = await apiFetch('/sync/push', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) });
  if (r && r.ok !== false) { await loadGitData(); toast('推送成功', 'ok'); }
  else toast('推送失败：' + (r && r.error ? r.error : '未知错误'), 'err');
}

async function commitGit() {
  if (!editor.activeDocId) return toast('请先选择文档', 'err');
  if (!commitMsg.trim()) return toast('请输入提交信息', 'err');
  const r = await apiFetch('/commit', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, message: commitMsg }) });
  if (r && r.ok) { commitMsg = ''; await loadGitData(); toast('提交成功', 'ok'); if (location.hash === '#/editor') renderEditor(); }
  else toast('提交失败', 'err');
}

async function syncRemote() {
  await pushGit();
  await pullGit();
}

// ── Remote management (settings page) ────────────────────────
async function addRemote() {
  const input = document.getElementById('newRemoteUrl');
  const url = input.value.trim();
  if (!url) return;
  if (!editor.activeDocId) return toast('请先在编辑器中打开一个文档', 'err');
  try {
    const r = await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, name: 'remote-' + Date.now().toString(36), url: url }) });
    if (r) { input.value = ''; toast('远端已添加', 'ok'); renderSetting(); }
  } catch (e) { toast('添加失败：' + e.message, 'err'); }
}

async function removeRemote(name) {
  if (!editor.activeDocId) return;
  await apiFetch('/sync/remote/' + encodeURIComponent(name), { method: 'DELETE', body: JSON.stringify({ doc_id: editor.activeDocId }) });
  renderSetting();
}

// ── Menu actions ─────────────────────────────────────────────
function setPanel(panel) {
  activePanel = panel;
  renderEditor();
  // 移动端点击面板按钮时自动展开侧边栏
  if (window.innerWidth < 992) {
    const el = document.getElementById('veSidebar');
    if (el && !el.classList.contains('show')) {
      el.classList.add('show');
      const bp = document.createElement('div');
      bp.className = 'offcanvas-backdrop fade';
      document.body.appendChild(bp);
      requestAnimationFrame(() => bp.classList.add('show'));
      document.body.classList.add('modal-open');
    }
  }
}

// 用事件委托管理 offcanvas，避免 DOM 重建后 Bootstrap 实例失效
function initOffcanvasDelegate() {
  // 关闭按钮：移除 show 类，隐藏 backdrop
  document.addEventListener('click', e => {
    if (!e.target.closest('#veSidebarClose')) return;
    const el = document.getElementById('veSidebar');
    if (el) {
      el.classList.remove('show');
      document.querySelector('.offcanvas-backdrop')?.remove();
      document.body.classList.remove('modal-open');
    }
  });
  // 触发按钮：手动控制开/关
  document.addEventListener('click', e => {
    if (!e.target.closest('#veSidebarToggler')) return;
    e.preventDefault();
    const el = document.getElementById('veSidebar');
    if (!el) return;
    if (el.classList.contains('show')) {
      el.classList.remove('show');
      document.querySelector('.offcanvas-backdrop')?.remove();
      document.body.classList.remove('modal-open');
    } else {
      el.classList.add('show');
      const bp = document.createElement('div');
      bp.className = 'offcanvas-backdrop fade';
      document.body.appendChild(bp);
      requestAnimationFrame(() => bp.classList.add('show'));
      document.body.classList.add('modal-open');
    }
  });
}
// 页面加载后只初始化一次
initOffcanvasDelegate();

// 菜单 offcanvas（编辑器和设置页共用同一套开/关逻辑）
function closeMenuOffcanvas() {
  ['veMenuOffcanvas', 'veSettingsMenuOffcanvas'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('show');
  });
  document.querySelector('.offcanvas-backdrop')?.remove();
  document.body.classList.remove('modal-open');
}

document.addEventListener('click', e => {
  // 编辑器页菜单触发 / 关闭
  if (e.target.closest('#veMenuToggler')) {
    e.preventDefault();
    const el = document.getElementById('veMenuOffcanvas');
    if (!el) return;
    if (el.classList.contains('show')) {
      el.classList.remove('show');
      document.querySelector('.offcanvas-backdrop')?.remove();
      document.body.classList.remove('modal-open');
    } else {
      el.classList.add('show');
      const bp = document.createElement('div');
      bp.className = 'offcanvas-backdrop fade';
      document.body.appendChild(bp);
      requestAnimationFrame(() => bp.classList.add('show'));
      document.body.classList.add('modal-open');
    }
    return;
  }
  if (e.target.closest('#veMenuClose')) {
    closeMenuOffcanvas();
    return;
  }
  // 设置页菜单触发 / 关闭
  if (e.target.closest('#veSettingsToggler')) {
    e.preventDefault();
    const el = document.getElementById('veSettingsMenuOffcanvas');
    if (!el) return;
    if (el.classList.contains('show')) {
      el.classList.remove('show');
      document.querySelector('.offcanvas-backdrop')?.remove();
      document.body.classList.remove('modal-open');
    } else {
      el.classList.add('show');
      const bp = document.createElement('div');
      bp.className = 'offcanvas-backdrop fade';
      document.body.appendChild(bp);
      requestAnimationFrame(() => bp.classList.add('show'));
      document.body.classList.add('modal-open');
    }
    return;
  }
  if (e.target.closest('#veSettingsMenuClose')) {
    closeMenuOffcanvas();
    return;
  }
});

function toggleDoc(docId) {
  expandedDocs[docId] = !expandedDocs[docId];
  renderEditor();
}

function logout() {
  auth.logout();
  Router.go('#/login');
}

// ── Modal helper ─────────────────────────────────────────────
function showModal(title, body, footer) {
  closeModal();
  const el = document.createElement('div');
  el.className = 'modal fade';
  el.id = 'veModal';
  el.tabIndex = -1;
  el.innerHTML =
    '<div class="modal-dialog modal-dialog-scrollable"><div class="modal-content">' +
      '<div class="modal-header py-2">' +
        '<h5 class="modal-title fs-6">' + title + '</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="关闭"></button>' +
      '</div>' +
      '<div class="modal-body">' + body + '</div>' +
      (footer ? '<div class="modal-footer py-2">' + footer + '</div>' : '') +
    '</div></div>';
  document.body.appendChild(el);
  el.addEventListener('hidden.bs.modal', () => el.remove());
  new bootstrap.Modal(el).show();
}

function closeModal() {
  const el = document.getElementById('veModal');
  if (el) { const m = bootstrap.Modal.getInstance(el); if (m) m.hide(); }
}

// ── 文件菜单：打开 / 导入 / 保存 / 另存为 ─────────────────────
function menuOpen() {
  if (sidebarDocs.length === 0) return showModal('打开文档', '<div class="text-secondary small">暂无文档，请先新建或导入</div>');
  const body = sidebarDocs.map(doc =>
    '<div class="fw-semibold small text-secondary mb-1">' + esc(doc.name) + '</div>' +
    ((doc.children || []).map(f =>
      '<button class="btn btn-sm btn-outline-secondary w-100 text-start mb-1" onclick="modalOpenFile(\'' + esc(doc.id) + '\',\'' + esc(f.path) + '\')">' +
        '<i class="bi bi-file-earmark-text me-1"></i>' + esc(f.path) +
      '</button>').join('') || '<div class="text-secondary small mb-2">（空）</div>')
  ).join('<hr class="my-2">');
  showModal('打开文档', body);
}

function modalOpenFile(docId, path) {
  closeModal();
  openFile(docId, path);
}

function menuImport() {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = '.md,.markdown,.txt';
  inp.multiple = true;
  inp.onchange = async () => {
    for (const f of inp.files) {
      const text = await f.text();
      await apiFetch('/docs', { method: 'POST', body: JSON.stringify({ name: f.name, content: text }) });
    }
    toast('导入完成', 'ok');
    await loadFiles();
    renderEditor();
  };
  inp.click();
}

async function saveNow() {
  if (!editor.activeDocId || !editor.activeFilePath) return toast('未打开文件', 'err');
  clearTimeout(saveTimer);
  const r = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath), {
    method: 'PUT', body: JSON.stringify({ content: editor.content })
  });
  if (r) {
    editor.unsaved = false;
    document.querySelectorAll('.ve-unsaved-dot').forEach(el => el.classList.add('d-none'));
    const ub = document.getElementById('veUnsavedBar');
    if (ub) ub.classList.add('d-none');
    toast('已保存', 'ok');
  }
}

async function menuSaveAs() {
  const name = prompt('另存为（新文档名，如 copy.md）：');
  if (!name) return;
  const r = await apiFetch('/docs', { method: 'POST', body: JSON.stringify({ name: name, content: editor.content }) });
  if (r) {
    await loadFiles();
    await openFile(r.id, r.name);
    toast('已另存为 ' + name, 'ok');
  }
}

// ── Git 菜单 ─────────────────────────────────────────────────
function needDoc() {
  if (!editor.activeDocId) { toast('请先打开一个文档', 'err'); return false; }
  return true;
}

async function menuGitConfig() {
  if (!needDoc()) return;
  const cfg = await apiFetch('/git/config?doc_id=' + encodeURIComponent(editor.activeDocId));
  showModal('设置 Git 基础信息',
    '<div class="mb-2"><label class="form-label small">user.name</label>' +
    '<input class="form-control form-control-sm" id="gName" value="' + esc(cfg.name) + '"></div>' +
    '<div class="mb-1"><label class="form-label small">user.email</label>' +
    '<input class="form-control form-control-sm" id="gEmail" value="' + esc(cfg.email) + '"></div>' +
    '<div class="text-secondary small">用于提交记录的作者身份，仅作用于当前文档仓库</div>',
    '<button class="btn btn-primary btn-sm" onclick="saveGitConfig()">保存</button>');
}

async function saveGitConfig() {
  const r = await apiFetch('/git/config', {
    method: 'POST',
    body: JSON.stringify({ doc_id: editor.activeDocId, name: document.getElementById('gName').value.trim(), email: document.getElementById('gEmail').value.trim() })
  });
  if (r && r.ok) { closeModal(); toast('Git 信息已保存', 'ok'); }
  else toast('保存失败', 'err');
}

async function menuRemotes() {
  if (!needDoc()) return;
  const list = await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) });
  const body =
    '<div class="input-group mb-3">' +
      '<input id="mRemoteUrl" class="form-control form-control-sm" placeholder="http://192.168.1.x:5000">' +
      '<button class="btn btn-primary btn-sm" onclick="modalAddRemote()"><i class="bi bi-plus-lg"></i></button>' +
    '</div>' +
    ((list || []).length ? list.map(r =>
      '<div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary-subtle small">' +
        '<i class="bi bi-router text-secondary"></i>' +
        '<span class="flex-grow-1 text-truncate">' + esc(r.name) + '</span>' +
        '<span class="text-secondary text-truncate" style="max-width:45%">' + esc(r.url) + '</span>' +
        '<button class="btn btn-sm btn-outline-danger py-0" onclick="modalDelRemote(\'' + esc(r.name) + '\')"><i class="bi bi-x-lg"></i></button>' +
      '</div>').join('') : '<div class="text-secondary small">暂无远端设备</div>');
  showModal('配置远程仓库', body);
}

async function modalAddRemote() {
  const url = document.getElementById('mRemoteUrl').value.trim();
  if (!url) return;
  await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, name: 'remote-' + Date.now().toString(36), url: url }) });
  closeModal();
  setTimeout(menuRemotes, 300);
}

async function modalDelRemote(name) {
  await apiFetch('/sync/remote/' + encodeURIComponent(name), { method: 'DELETE', body: JSON.stringify({ doc_id: editor.activeDocId }) });
  closeModal();
  setTimeout(menuRemotes, 300);
}

async function menuNewBranch() {
  if (!needDoc()) return;
  showModal('添加新分支',
    '<div class="mb-1"><label class="form-label small">分支名</label>' +
    '<input class="form-control form-control-sm" id="nbName" placeholder="feature-xxx"></div>' +
    '<div class="text-secondary small">将从当前分支创建并切换过去</div>',
    '<button class="btn btn-primary btn-sm" onclick="createBranch()">创建</button>');
}

async function createBranch() {
  const name = document.getElementById('nbName').value.trim();
  if (!name) return;
  if (editor.unsaved) await saveNow();
  const r = await apiFetch('/git/branch', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, name: name, action: 'create' }) });
  if (r && r.ok) { closeModal(); editor.gitBranch = name; renderEditor(); toast('已创建并切换到 ' + name, 'ok'); }
  else toast('创建失败：' + (r ? r.error : ''), 'err');
}

async function menuSwitchBranch() {
  if (!needDoc()) return;
  const list = await apiFetch('/git/branches?doc_id=' + encodeURIComponent(editor.activeDocId));
  const body = list.length ? list.map(b =>
    '<button class="btn btn-sm btn-outline-secondary w-100 text-start mb-1" onclick="switchBranch(\'' + esc(b.name) + '\')">' +
      '<i class="bi ' + (b.current ? 'bi-check2-circle' : 'bi-circle') + ' me-1"></i>' + esc(b.name) +
      (b.current ? '<span class="text-secondary small ms-1">（当前）</span>' : '') +
    '</button>').join('') : '<div class="text-secondary small">暂无分支</div>';
  showModal('切换分支', body);
}

async function switchBranch(name) {
  if (editor.unsaved) await saveNow();
  const r = await apiFetch('/git/branch', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, name: name, action: 'switch' }) });
  if (r && r.ok) {
    closeModal();
    editor.gitBranch = name;
    if (editor.activeFilePath) {
      const cur = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath));
      if (cur) { editor.content = cur.content; editor.fileSha = cur.sha; editor.unsaved = false; }
    }
    await loadGitData();
    renderEditor();
    toast('已切换到 ' + name, 'ok');
  } else toast('切换失败：' + (r ? r.error : ''), 'err');
}

async function menuMergeBranch() {
  if (!needDoc()) return;
  const list = await apiFetch('/git/branches?doc_id=' + encodeURIComponent(editor.activeDocId));
  const others = list.filter(b => !b.current);
  const body = others.length ? others.map(b =>
    '<button class="btn btn-sm btn-outline-secondary w-100 text-start mb-1" onclick="mergeBranch(\'' + esc(b.name) + '\')">' +
      '<i class="bi bi-sign-merge-left me-1"></i>合并 ' + esc(b.name) + ' 到当前分支' +
    '</button>').join('') : '<div class="text-secondary small">没有可合并的其他分支</div>';
  showModal('合并分支', body);
}

async function mergeBranch(name) {
  if (editor.unsaved) await saveNow();
  const r = await apiFetch('/git/merge', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, branch: name }) });
  if (r && r.ok) {
    closeModal();
    await loadGitData();
    if (editor.activeFilePath) {
      const cur = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath));
      if (cur) { editor.content = cur.content; editor.unsaved = false; }
    }
    renderEditor();
    toast('合并成功', 'ok');
  } else toast('合并失败：' + (r ? r.error : ''), 'err');
}

async function menuReset() {
  if (!needDoc()) return;
  const list = await apiFetch('/history/' + editor.activeDocId + '?count=30');
  const body = list.length ? list.map(c =>
    '<div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary-subtle small">' +
      '<i class="bi bi-circle-fill text-secondary" style="font-size:7px"></i>' +
      '<span class="flex-grow-1 text-truncate">' + esc(c.message) + '</span>' +
      '<span class="text-secondary">' + esc(c.sha.slice(0, 7)) + '</span>' +
      '<button class="btn btn-sm btn-outline-warning py-0" onclick="resetTo(\'' + esc(c.sha) + '\')">回退</button>' +
    '</div>').join('') : '<div class="text-secondary small">暂无提交记录</div>';
  showModal('回退版本（--hard，未提交的更改会丢失）', body);
}

async function resetTo(sha) {
  if (!confirm('确定回退到 ' + sha.slice(0, 7) + '？当前未提交的更改将丢失。')) return;
  const r = await apiFetch('/git/reset', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId, sha: sha }) });
  if (r && r.ok) {
    closeModal();
    if (editor.activeFilePath) {
      const cur = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath));
      if (cur) { editor.content = cur.content; editor.unsaved = false; }
    }
    await loadGitData();
    renderEditor();
    toast('已回退到 ' + sha.slice(0, 7), 'ok');
  } else toast('回退失败：' + (r ? r.error : ''), 'err');
}

// ── 可拖拽布局 ───────────────────────────────────────────────
const layout = {
  sidebarW: parseInt(localStorage.getItem('ve_sidebar_w') || '280', 10),
  editorPct: parseInt(localStorage.getItem('ve_editor_pct') || '50', 10)
};

function applyLayout() {
  const sb = document.getElementById('veSidebar');
  if (sb) sb.style.width = layout.sidebarW + 'px';
  const ed = document.getElementById('veEditorPane');
  if (ed) ed.style.flex = '0 0 ' + layout.editorPct + '%';
}

function initResizers() {
  const s1 = document.getElementById('veSidebarResizer');
  if (s1) s1.onpointerdown = e => startResize(e, 'sidebar');
  const s2 = document.getElementById('veSplitResizer');
  if (s2) s2.onpointerdown = e => startResize(e, 'split');
}

function startResize(e, kind) {
  e.preventDefault();
  const handle = e.currentTarget;
  handle.classList.add('active');
  handle.setPointerCapture && handle.setPointerCapture(e.pointerId);
  const startX = e.clientX;
  const startW = layout.sidebarW, startPct = layout.editorPct;
  const onMove = ev => {
    if (kind === 'sidebar') {
      layout.sidebarW = Math.min(600, Math.max(160, startW + ev.clientX - startX));
      const sb = document.getElementById('veSidebar');
      if (sb) sb.style.width = layout.sidebarW + 'px';
    } else {
      const split = document.querySelector('.ve-split');
      if (split) {
        const rect = split.getBoundingClientRect();
        layout.editorPct = Math.min(85, Math.max(15, ((ev.clientX - rect.left) / rect.width) * 100));
        const ed = document.getElementById('veEditorPane');
        if (ed) ed.style.flex = '0 0 ' + layout.editorPct + '%';
      }
    }
  };
  const onUp = () => {
    handle.classList.remove('active');
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    localStorage.setItem('ve_sidebar_w', String(Math.round(layout.sidebarW)));
    localStorage.setItem('ve_editor_pct', String(Math.round(layout.editorPct)));
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

function onFontSizeChange(val) {
  fontSize = parseInt(val, 10);
  localStorage.setItem('ve_font_size', String(fontSize));
  document.documentElement.style.setProperty('--ed-font-size', fontSize + 'px');
}

function toggleMobilePreview() {
  if (window.innerWidth >= 768) return;
  mobilePreviewMode = !mobilePreviewMode;
  localStorage.setItem('ve_mobile_preview', mobilePreviewMode ? '1' : '0');
  applyMobilePreviewState();
}

function applyMobilePreviewState() {
  const ep = document.getElementById('veEditorPane');
  const pr = document.getElementById('vePreview');
  const btn = document.getElementById('vePreviewToggle');
  if (!ep || !pr) return;
  if (window.innerWidth < 768) {
    if (mobilePreviewMode) {
      ep.classList.add('d-none');
      pr.classList.remove('d-none');
      pr.style.display = '';
      const scrollEl = pr.querySelector('.ve-scroll');
      if (scrollEl) scrollEl.innerHTML = parseMd(editor.content || '');
      else pr.innerHTML = '<div class="ve-scroll">' + parseMd(editor.content || '') + '</div>';
    } else {
      ep.classList.remove('d-none');
      pr.classList.add('d-none');
      pr.style.display = '';
    }
    if (btn) {
      btn.innerHTML = '<i class="bi bi-' + (mobilePreviewMode ? 'pencil' : 'eye') + '"></i>' + (mobilePreviewMode ? ' 编辑' : ' 预览');
    }
  } else {
    // 桌面端：尊重 previewVisible 状态
    ep.classList.remove('d-none');
    if (previewVisible) {
      if (!document.getElementById('vePreview')) {
        const split = document.querySelector('.ve-split');
        const resizer = document.getElementById('veSplitResizer');
        const pr = document.createElement('div');
        pr.className = 'pane ve-preview';
        pr.id = 'vePreview';
        pr.innerHTML = '<div class="ve-scroll">' + parseMd(editor.content || '') + '</div>';
        (resizer || split).appendChild(pr);
      }
    } else {
      const existing = document.getElementById('vePreview');
      if (existing) existing.remove();
    }
  }
}

// ── Editor page ──────────────────────────────────────────────
function renderEditor() {
  const app = document.getElementById('app');
  const fileName = editor.activeFilePath ? editor.activeFilePath.split('/').pop() : '';

  const filesPanel =
    '<div class="d-flex justify-content-between align-items-center px-3 py-2 border-bottom border-secondary-subtle">' +
      '<span class="text-uppercase text-secondary" style="font-size:11px;letter-spacing:1px">资源管理器</span>' +
      '<span>' +
        '<button class="btn btn-sm btn-outline-secondary me-1" title="新建文件" onclick="createFile()"><i class="bi bi-file-earmark-plus"></i></button>' +
        '<button class="btn btn-sm btn-outline-secondary me-1" title="新建文件夹" onclick="createFolder()"><i class="bi bi-folder-plus"></i></button>' +
        '<button class="btn btn-sm btn-outline-secondary me-1" title="更换工作区" onclick="openWorkspaceModal()"><i class="bi bi-folder-symlink"></i></button>' +
        (editor.activeDocId ? '<button class="btn btn-sm btn-outline-danger" title="删除当前文档" onclick="deleteDoc(editor.activeDocId)"><i class="bi bi-trash3"></i></button>' : '') +
      '</span>' +
    '</div>' +
    '<div class="ve-scroll py-1">' +
      // 工作区列表
       (workspaces.length > 0 ?
         '<div class="px-3 py-2 border-bottom border-secondary-subtle">' +
           '<span class="text-uppercase text-secondary" style="font-size:11px;letter-spacing:1px">工作区</span>' +
         '</div>' +
         workspaces.map(ws => {
           const wsFiles = wsFileCache[ws.id] || [];
           const isActive = editor.activeDocId === ws.id;
           return '<div>' +
             '<div class="ve-tree-item' + (isActive ? ' on' : '') + '" onclick="selectWorkspace(\'' + esc(ws.id) + '\')">' +
               '<i class="bi bi-folder2-open"></i>' +
               '<span class="nm" title="' + esc(ws.source_path || '') + '">' + esc(ws.name) + '</span>' +
               '<span class="text-secondary small">' + wsFiles.length + '</span>' +
               '<button class="btn btn-sm py-0 text-secondary" style="font-size:11px;margin-left:2px" onclick="event.stopPropagation();closeWorkspace(\'' + esc(ws.id) + '\')" title="关闭工作区"><i class="bi bi-x"></i></button>' +
             '</div>' +
             (isActive && wsFiles.length > 0 ? wsFiles.map(f =>
               '<div class="ve-tree-item ps-4' + (editor.activeFilePath === f.path ? ' on' : '') + '" onclick="openFile(\'' + esc(ws.id) + '\',\'' + esc(f.path) + '\')">' +
                 '<i class="bi ' + (f.path.endsWith('.md') ? 'bi-file-earmark-text' : 'bi-file-earmark') + '"></i>' +
                 '<span class="nm">' + esc(f.path.split('/').pop()) + '</span>' +
               '</div>').join('') : '') +
           '</div>';
         }).join('') :
         '<div class="px-3 py-2 text-secondary small">点击右上角 <i class="bi bi-folder-open"></i> 按钮打开工作区</div>') +
       (workspaces.length > 0 ? '<hr class="my-1">' : '') +
      (sidebarDocs.length === 0 ?
        '<div class="px-3 py-2 text-secondary small">暂无文档，点击右上角新建</div>' :
        sidebarDocs.map(doc =>
          '<div>' +
            '<div class="ve-tree-item" onclick="toggleDoc(\'' + esc(doc.id) + '\')">' +
              '<i class="bi ' + (expandedDocs[doc.id] ? 'bi-folder2-open' : 'bi-folder') + '"></i>' +
              '<span class="nm">' + esc(doc.name) + '</span>' +
              '<span class="text-secondary small">' + (doc.file_count || 0) + '</span>' +
            '</div>' +
            (expandedDocs[doc.id] && doc.children ? doc.children.map(f =>
              '<div class="ve-tree-item ps-4' + (editor.activeDocId === doc.id && editor.activeFilePath === f.path ? ' on' : '') + '" onclick="openFile(\'' + esc(doc.id) + '\',\'' + esc(f.path) + '\')">' +
                '<i class="bi ' + (f.path.endsWith('.md') ? 'bi-file-earmark-text' : 'bi-file-earmark') + '"></i>' +
                '<span class="nm">' + esc(f.path.split('/').pop()) + '</span>' +
              '</div>').join('') : '') +
          '</div>').join('')) +
    '</div>';

  const gitPanel =
    '<div class="d-flex justify-content-between align-items-center px-3 py-2 border-bottom border-secondary-subtle">' +
      '<span class="text-uppercase text-secondary" style="font-size:11px;letter-spacing:1px">版本管理 Git</span>' +
      '<span class="badge text-bg-secondary"><i class="bi bi-diagram-3 me-1"></i>' + esc(editor.gitBranch || 'main') + '</span>' +
    '</div>' +
    '<div class="ve-scroll p-3">' +
      '<div class="d-flex gap-2 mb-2">' +
        '<button class="btn btn-sm btn-primary flex-fill" onclick="commitGit()"><i class="bi bi-check2-circle me-1"></i>提交</button>' +
        '<button class="btn btn-sm btn-outline-secondary flex-fill" onclick="pullGit()"><i class="bi bi-cloud-download me-1"></i>拉取</button>' +
        '<button class="btn btn-sm btn-outline-secondary flex-fill" onclick="pushGit()"><i class="bi bi-cloud-upload me-1"></i>推送</button>' +
      '</div>' +
      '<label class="form-label small text-secondary">提交信息</label>' +
      '<textarea class="form-control form-control-sm mb-2" rows="2" placeholder="描述本次更改..." oninput="commitMsg=this.value">' + esc(commitMsg) + '</textarea>' +
      '<button class="btn btn-sm btn-outline-success w-100 mb-3" onclick="syncRemote()"><i class="bi bi-arrow-repeat me-1"></i>推送并拉取（同步）</button>' +
      '<div class="text-uppercase text-secondary mb-1" style="font-size:11px;letter-spacing:1px">最近提交</div>' +
      (commits.length === 0 ?
        '<div class="text-secondary small">暂无提交记录</div>' :
        commits.map(c =>
          '<div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary-subtle small">' +
            '<i class="bi bi-circle-fill text-secondary" style="font-size:7px"></i>' +
            '<span class="flex-grow-1 text-truncate">' + esc(c.message) + '</span>' +
            '<span class="text-secondary">' + esc(c.date ? String(c.date).split(' ')[0] : '') + '</span>' +
          '</div>').join('')) +
    '</div>';

  app.innerHTML =
    // top navbar
    '<nav class="navbar navbar-expand-lg bg-body-tertiary border-bottom border-secondary-subtle px-2 py-1 flex-shrink-0">' +
      '<div class="container-fluid">' +
        '<a class="navbar-brand ve-brand mb-0" href="#/editor"><i class="bi bi-journal-richtext me-1"></i><span class="ve-logo-text">VanillaEditor</span></a>' +
        '<button class="navbar-toggler border-0 shadow-none d-lg-none" type="button" id="veMenuToggler" aria-label="打开菜单">' +
          '<i class="bi bi-list"></i>' +
        '</button>' +
        '<div class="collapse navbar-collapse" id="veNav">' +
          '<ul class="navbar-nav me-auto">' +
            '<li class="nav-item dropdown">' +
              '<a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown" role="button" aria-expanded="false"><i class="bi bi-folder2 me-1"></i>文件</a>' +
              '<ul class="dropdown-menu">' +
                '<li><a class="dropdown-item" href="#" onclick="menuOpen();return false"><i class="bi bi-folder2-open me-2"></i>打开</a></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuImport();return false"><i class="bi bi-box-arrow-in-down me-2"></i>导入</a></li>' +
                '<li><hr class="dropdown-divider"></li>' +
                '<li><a class="dropdown-item" href="#" onclick="saveNow();return false"><i class="bi bi-save me-2"></i>保存</a></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuSaveAs();return false"><i class="bi bi-save2 me-2"></i>另存为</a></li>' +
              '</ul>' +
            '</li>' +
            '<li class="nav-item dropdown">' +
              '<a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown" role="button" aria-expanded="false"><i class="bi bi-git me-1"></i>Git</a>' +
              '<ul class="dropdown-menu">' +
                '<li><a class="dropdown-item" href="#" onclick="menuGitConfig();return false"><i class="bi bi-person-vcard me-2"></i>设置 Git 基础信息</a></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuRemotes();return false"><i class="bi bi-hdd-network me-2"></i>配置远程仓库</a></li>' +
                '<li><hr class="dropdown-divider"></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuNewBranch();return false"><i class="bi bi-plus-square me-2"></i>添加新分支</a></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuSwitchBranch();return false"><i class="bi bi-arrow-left-right me-2"></i>切换分支</a></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuMergeBranch();return false"><i class="bi bi-sign-merge-left me-2"></i>合并分支</a></li>' +
                '<li><hr class="dropdown-divider"></li>' +
                '<li><a class="dropdown-item" href="#" onclick="menuReset();return false"><i class="bi bi-arrow-counterclockwise me-2"></i>回退版本</a></li>' +
              '</ul>' +
            '</li>' +
            '<li class="nav-item"><a class="nav-link" href="#/setting"><i class="bi bi-gear me-1"></i>设置</a></li>' +
          '</ul>' +
          '<div class="dropdown">' +
            '<a class="nav-link dropdown-toggle p-0" href="#" data-bs-toggle="dropdown" role="button" aria-expanded="false">' +
              '<i class="bi bi-person-circle me-1"></i>' + esc(auth.username) +
            '</a>' +
            '<ul class="dropdown-menu dropdown-menu-end">' +
              '<li><a class="dropdown-item" href="#/setting"><i class="bi bi-person-badge me-2"></i>用户信息与设置</a></li>' +
              '<li><hr class="dropdown-divider"></li>' +
              '<li><a class="dropdown-item" href="#" onclick="logout();return false"><i class="bi bi-box-arrow-right me-2"></i>退出登录</a></li>' +
            '</ul>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</nav>' +

    // left-side menu offcanvas (mobile only)
    '<div class="offcanvas offcanvas-start d-lg-none" tabindex="-1" id="veMenuOffcanvas" aria-labelledby="veMenuOffcanvasLabel">' +
      '<div class="offcanvas-header border-bottom border-secondary-subtle">' +
        '<h6 class="offcanvas-title text-uppercase text-secondary" id="veMenuOffcanvasLabel" style="font-size:11px;letter-spacing:1px">菜单</h6>' +
        '<button type="button" class="btn-close" id="veMenuClose" aria-label="关闭"></button>' +
      '</div>' +
      '<div class="offcanvas-body p-0">' +
        '<ul class="list-unstyled mb-0">' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuOpen();closeMenuOffcanvas();return false"><i class="bi bi-folder2-open me-2"></i>打开文档</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuImport();closeMenuOffcanvas();return false"><i class="bi bi-box-arrow-in-down me-2"></i>导入</a></li>' +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="saveNow();closeMenuOffcanvas();return false"><i class="bi bi-save me-2"></i>保存</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuSaveAs();closeMenuOffcanvas();return false"><i class="bi bi-save2 me-2"></i>另存为</a></li>' +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuGitConfig();closeMenuOffcanvas();return false"><i class="bi bi-person-vcard me-2"></i>设置 Git 基础信息</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuRemotes();closeMenuOffcanvas();return false"><i class="bi bi-hdd-network me-2"></i>配置远程仓库</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuNewBranch();closeMenuOffcanvas();return false"><i class="bi bi-plus-square me-2"></i>添加新分支</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuSwitchBranch();closeMenuOffcanvas();return false"><i class="bi bi-arrow-left-right me-2"></i>切换分支</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuMergeBranch();closeMenuOffcanvas();return false"><i class="bi bi-sign-merge-left me-2"></i>合并分支</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="menuReset();closeMenuOffcanvas();return false"><i class="bi bi-arrow-counterclockwise me-2"></i>回退版本</a></li>' +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#/setting"><i class="bi bi-gear me-2"></i>设置</a></li>' +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#/setting"><i class="bi bi-person-badge me-2"></i>用户信息与设置</a></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="logout();closeMenuOffcanvas();return false"><i class="bi bi-box-arrow-right me-2"></i>退出登录</a></li>' +
        '</ul>' +
      '</div>' +
    '</div>' +

    '<div class="d-flex flex-grow-1 overflow-hidden">' +
      // sidebar (offcanvas below lg)
      '<aside class="offcanvas-lg offcanvas-start border-end border-secondary-subtle ve-sidebar" tabindex="-1" id="veSidebar" aria-labelledby="veSidebarLabel">' +
        '<div class="offcanvas-header d-lg-none py-1 border-bottom border-secondary-subtle">' +
          '<span class="text-uppercase text-secondary" id="veSidebarLabel" style="font-size:11px">' + (activePanel === 'git' ? 'Git' : '资源管理器') + '</span>' +
          '<button type="button" class="btn-close" id="veSidebarClose" aria-label="关闭"></button>' +
        '</div>' +
        '<div class="offcanvas-body d-flex p-0">' +
          '<div class="ve-abar d-none d-lg-flex">' +
            '<div class="ib' + (activePanel === 'files' ? ' on' : '') + '" title="资源管理器" onclick="setPanel(\'files\')"><i class="bi bi-files"></i></div>' +
            '<div class="ib' + (activePanel === 'git' ? ' on' : '') + '" title="Git 版本管理" onclick="setPanel(\'git\')"><i class="bi bi-git"></i></div>' +
          '</div>' +
          '<div class="panel">' + (activePanel === 'git' ? gitPanel : filesPanel) + '</div>' +
        '</div>' +
      '</aside>' +
      '<div class="ve-resizer ve-resizer-v d-none d-lg-block" id="veSidebarResizer" title="拖动调整侧边栏宽度"></div>' +

      // main area
      '<main class="flex-grow-1 d-flex flex-column overflow-hidden">' +
        '<div class="d-flex align-items-center gap-2 px-3 py-1 bg-body-tertiary border-bottom border-secondary-subtle flex-shrink-0">' +
          '<button class="btn btn-sm btn-outline-secondary py-0 d-lg-none" onclick="setPanel(\'files\')" title="文件列表"><i class="bi bi-list"></i></button>' +
          '<button class="btn btn-sm btn-outline-secondary py-0 d-lg-none" onclick="setPanel(\'git\')" title="Git 面板"><i class="bi bi-git"></i></button>' +
          '<span class="ms-auto">' +
            '<button class="btn btn-sm btn-outline-secondary py-0 d-md-none" id="vePreviewToggle" onclick="toggleMobilePreview()" title="切换预览/编辑">' +
              '<i class="bi bi-' + (mobilePreviewMode ? 'pencil' : 'eye') + '"></i>' +
              (mobilePreviewMode ? ' 编辑' : ' 预览') +
            '</button>' +
            '<button class="btn btn-sm btn-outline-secondary py-0 d-none d-md-inline-flex" id="vePreviewToggleDesktop" onclick="togglePreview()" title="切换预览">' +
              '<i class="bi bi-eye"></i>' +
            '</button>' +
          '</span>' +
        '</div>' +
        // 标签栏
        '<div class="d-flex align-items-end border-bottom flex-shrink-0 ve-tabs" style="overflow-x:auto;background:var(--bs-body-bg)">' +
          (openTabs.length === 0 ?
            '<div class="text-secondary small px-2 py-1">未打开文件</div>' :
            openTabs.map(t => {
              const isActive = t.id === activeTabId;
              const label = esc(t.label);
              return '<div class="d-flex align-items-center gap-1 px-2 py-1 small ve-tab border-end border-secondary-subtle" style="cursor:pointer;white-space:nowrap;min-width:80px;max-width:200px;border-bottom:2px solid ' + (isActive ? 'var(--ve-accent)' : 'transparent') + ';background:' + (isActive ? 'var(--bs-body-bg)' : 'transparent') + '" onclick="switchTab(\'' + esc(t.id) + '\')">' +
                '<i class="bi bi-file-earmark-text text-secondary" style="font-size:11px"></i>' +
                '<span class="flex-grow-1 text-truncate' + (isActive ? '' : ' text-secondary') + '">' + label + '</span>' +
                '<span class="ve-unsaved-dot' + (t.unsaved ? '' : ' d-none') + '" title="未保存"></span>' +
                '<span class="ve-tab-close" onclick="event.stopPropagation();closeTab(\'' + esc(t.id) + '\')"><i class="bi bi-x"></i></span>' +
              '</div>';
            }).join('')
          ) +
        '</div>' +

          '<div class="ve-split">' +
            '<div class="pane d-flex flex-column ve-edp" id="veEditorPane">' +
              '<div class="ve-editor-area">' +
                '<div class="ve-lngutter"><div class="ve-lngutter-inner" id="veLnNums"></div></div>' +
                '<div class="ve-editor-scroll">' +
                  '<pre class="ve-hl" id="veHighlight" aria-hidden="true"></pre>' +
                  '<textarea class="ve-editor" id="veEditor" spellcheck="false" placeholder="在此输入 Markdown..."></textarea>' +
                '</div>' +
              '</div>' +
            '</div>' +
            '<div class="ve-resizer ve-resizer-v d-none d-md-block" id="veSplitResizer" title="拖动调整编辑/预览宽度"></div>' +
            (previewVisible ? '<div class="pane ve-preview" id="vePreview"><div class="ve-scroll">' + parseMd(editor.content || '') + '</div></div>' : '') +
          '</div>' +
      '</main>' +
    '</div>' +

    // status bar
    '<div class="d-flex align-items-center gap-3 px-3 flex-shrink-0 text-white small" style="height:24px;background:var(--bs-primary-bg-subtle);background-color:#0d6efd">' +
      '<span><i class="bi bi-diagram-3 me-1"></i>' + esc(editor.gitBranch || 'main') + '</span>' +
      (editor.fileSha ? '<span><i class="bi bi-hash me-1"></i>' + esc(editor.fileSha.slice(0, 7)) + '</span>' : '') +
       '<span class="d-flex align-items-center' + (editor.unsaved ? '' : ' d-none') + '" id="veUnsavedBar"><span class="ve-unsaved-dot me-1"></span>有未保存更改</span>' +
      '<span class="ms-auto">VanillaEditor v0.1.3</span>' +
      '<span id="veClock">' + new Date().toLocaleTimeString() + '</span>' +
    '</div>';

  const ta = document.getElementById('veEditor');
  if (ta) {
    ta.value = editor.content;
    renderHighlight(ta.value);
    ta.addEventListener('input', e => {
      editor.content = e.target.value;
      editor.unsaved = true;
      const pv = document.getElementById('vePreview');
      if (pv && !pv.classList.contains('d-none')) {
        const scrollEl = pv.querySelector('.ve-scroll');
        if (scrollEl) scrollEl.innerHTML = parseMd(editor.content);
        else pv.innerHTML = '<div class="ve-scroll">' + parseMd(editor.content) + '</div>';
      }
      renderHighlight(editor.content);
      // 同步标签页未保存状态
      const tab = openTabs.find(t => t.id === activeTabId);
      if (tab) tab.unsaved = editor.unsaved;
      document.querySelectorAll('.ve-unsaved-dot').forEach(el => el.classList.toggle('d-none', !editor.unsaved));
      const ub = document.getElementById('veUnsavedBar');
      if (ub) ub.classList.toggle('d-none', !editor.unsaved);
      clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        if (!editor.activeDocId || !editor.activeFilePath) return;
        const r = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath), {
          method: 'PUT', body: JSON.stringify({ content: editor.content })
        });
        if (r) {
          editor.unsaved = false;
          if (tab) tab.unsaved = false;
          document.querySelectorAll('.ve-unsaved-dot').forEach(el => el.classList.add('d-none'));
          if (ub) ub.classList.add('d-none');
          toast('已保存', 'ok');
        }
      }, 1500);
    });
    ta.addEventListener('keydown', e => {
      if (e.key !== 'Tab') return;
      e.preventDefault();
      const s = ta.selectionStart, en = ta.selectionEnd;
      ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(en);
      ta.selectionStart = ta.selectionEnd = s + 2;
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // 滚动同步：高亮层 + 行号 + 预览区
    const lnEl = document.getElementById('veLnNums');
    ta.addEventListener('scroll', () => {
      const hlEl = document.getElementById('veHighlight');
      if (hlEl) { hlEl.scrollTop = ta.scrollTop; hlEl.scrollLeft = ta.scrollLeft; }
      if (lnEl) { lnEl.scrollTop = ta.scrollTop; }
      const pvScroll = document.querySelector('#vePreview .ve-scroll');
      if (pvScroll) { pvScroll.scrollTop = ta.scrollTop; pvScroll.scrollLeft = ta.scrollLeft; }
    });
  }
  applyLayout();
  initResizers();
  applyMobilePreviewState();
  if (activePanel === 'git') loadGitData();
}

// ── Settings page ────────────────────────────────────────────
let currentSettingTab = 'account';

async function renderSetting() {
  const app = document.getElementById('app');
  let me = null;
  try { me = await apiFetch('/auth/me'); } catch (e) {}
  if (!me) return;

  const menuItems = [
    { id: 'account', icon: 'bi-person-badge', label: '账号管理' },
    { id: 'network', icon: 'bi-shield-lock', label: '网络与安全' },
    { id: 'version', icon: 'bi-git', label: '版本管理与同步' },
    { id: 'about', icon: 'bi-info-circle', label: '关于' },
  ];

  function renderContent(tab) {
    switch (tab) {
      case 'account':
        return '<div class="card h-100">' +
          '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-person-badge me-1"></i>账号信息</div>' +
          '<div class="card-body">' +
            '<div class="d-flex align-items-center mb-4">' +
              '<i class="bi bi-person-circle fs-1 me-3 text-secondary"></i>' +
              '<div>' +
                '<div class="fw-semibold fs-5">' + esc(me.username) + '</div>' +
                '<div class="text-secondary small">本地账号，数据存储于 data/' + esc(me.username) + '/</div>' +
              '</div>' +
            '</div>' +
            '<button class="btn btn-outline-danger w-100" onclick="logout()"><i class="bi bi-box-arrow-right me-1"></i>退出登录</button>' +
          '</div>' +
        '</div>';
       case 'network':
         return '<div class="card h-100">' +
           '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-shield-lock me-1"></i>远程访问控制</div>' +
           '<div class="card-body">' +
             '<p class="text-secondary small">远程控制功能开发中，敬请期待。</p>' +
           '</div>' +
           '<div class="card-header bg-transparent border-secondary-subtle mt-3"><i class="bi bi-hdd-network me-1"></i>同步远端设备</div>' +
           '<div class="card-body" id="veRemoteListBody">' +
             '<p class="text-secondary small">加载中…</p>' +
           '</div>' +
         '</div>';
      case 'version':
        return '<div class="card h-100">' +
          '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-git me-1"></i>Git 版本管理</div>' +
          '<div class="card-body">' +
            '<p class="text-secondary small mb-3">当前作用文档：' +
              (editor.activeDocId ? '<span class="badge text-bg-secondary ms-1">' + esc(editor.activeDocId) + '</span>' : '<span class="text-warning ms-1">未选择</span>') +
            '</p>' +
            '<div class="d-grid gap-2">' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuGitConfig()"><i class="bi bi-person-vcard me-2"></i>设置 Git 基础信息</button>' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuRemotes()"><i class="bi bi-hdd-network me-2"></i>配置远程仓库</button>' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuNewBranch()"><i class="bi bi-plus-square me-2"></i>添加新分支</button>' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuSwitchBranch()"><i class="bi bi-arrow-left-right me-2"></i>切换分支</button>' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuMergeBranch()"><i class="bi bi-sign-merge-left me-2"></i>合并分支</button>' +
              '<button class="btn btn-outline-secondary text-start" onclick="menuReset()"><i class="bi bi-arrow-counterclockwise me-2"></i>回退版本</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      case 'about':
        return '<div class="card h-100">' +
          '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-info-circle me-1"></i>关于</div>' +
          '<div class="card-body">' +
            '<div class="d-flex align-items-center mb-3">' +
              '<i class="bi bi-journal-richtext fs-1 me-3" style="color:var(--ve-accent)"></i>' +
              '<div>' +
                '<div class="fw-semibold fs-5" style="color:var(--ve-accent)">VanillaEditor</div>' +
                '<div class="text-secondary small">v0.1.0 — 分布式离线 Markdown 编辑器</div>' +
              '</div>' +
            '</div>' +
            '<p class="text-secondary small">每台设备独立运行，数据完全存储在本地，通过 Git 协议实现设备间端到端同步，无需任何第三方服务器。</p>' +
            '<hr class="border-secondary-subtle">' +
            '<div class="text-secondary small">' +
              '<div><i class="bi bi-check2 me-1"></i>完全离线可用</div>' +
              '<div><i class="bi bi-check2 me-1"></i>端到端 Git 同步</div>' +
              '<div><i class="bi bi-check2 me-1"></i>版本回溯与分支管理</div>' +
              '<div><i class="bi bi-check2 me-1"></i>工作区支持（本地目录直接打开）</div>' +
            '</div>' +
          '</div>' +
        '</div>';
      default: return '';
    }
  }

  app.innerHTML =
    '<nav class="navbar navbar-expand-lg bg-body-tertiary border-bottom border-secondary-subtle px-2 py-1 flex-shrink-0">' +
      '<div class="container-fluid">' +
        '<a class="navbar-brand ve-brand mb-0" href="#/editor"><i class="bi bi-journal-richtext me-1"></i><span class="ve-logo-text">VanillaEditor</span></a>' +
        '<button class="navbar-toggler border-0 shadow-none d-lg-none" type="button" id="veSettingsToggler" aria-label="展开菜单">' +
          '<i class="bi bi-list"></i>' +
        '</button>' +
        '<div class="collapse navbar-collapse" id="veSettingsNav">' +
          '<ul class="navbar-nav me-auto">' +
            '<li class="nav-item"><a class="nav-link" href="#/editor"><i class="bi bi-pencil-square me-1"></i>编辑器</a></li>' +
            '<li class="nav-item"><a class="nav-link active" href="#/setting"><i class="bi bi-gear me-1"></i>设置</a></li>' +
          '</ul>' +
          '<div class="dropdown">' +
            '<a class="nav-link dropdown-toggle p-0" href="#" data-bs-toggle="dropdown" role="button" aria-expanded="false">' +
              '<i class="bi bi-person-circle me-1"></i>' + esc(auth.username) +
            '</a>' +
            '<ul class="dropdown-menu dropdown-menu-end">' +
              '<li><a class="dropdown-item" href="#" onclick="logout();return false"><i class="bi bi-box-arrow-right me-2"></i>退出登录</a></li>' +
            '</ul>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</nav>' +

    // mobile settings menu offcanvas
    '<div class="offcanvas offcanvas-end d-lg-none" tabindex="-1" id="veSettingsMenuOffcanvas" aria-labelledby="veSettingsMenuOffcanvasLabel">' +
      '<div class="offcanvas-header border-bottom border-secondary-subtle">' +
        '<h6 class="offcanvas-title text-uppercase text-secondary" id="veSettingsMenuOffcanvasLabel" style="font-size:11px;letter-spacing:1px">设置</h6>' +
        '<button type="button" class="btn-close" id="veSettingsMenuClose" aria-label="关闭"></button>' +
      '</div>' +
      '<div class="offcanvas-body p-0">' +
        '<ul class="list-unstyled mb-0">' +
          menuItems.map(m => '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="switchSettingTab(\'' + m.id + '\');closeSettingsMenu()"><i class="bi bi-' + m.icon + ' me-2"></i>' + m.label + '</a></li>').join('') +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#/editor"><i class="bi bi-pencil-square me-2"></i>编辑器</a></li>' +
          '<li><hr class="dropdown-divider my-0"></li>' +
          '<li><a class="dropdown-item d-block py-3 px-4 text-body" href="#" onclick="logout()"><i class="bi bi-box-arrow-right me-2"></i>退出登录</a></li>' +
        '</ul>' +
      '</div>' +
    '</div>' +

    '<div class="d-flex flex-grow-1 overflow-hidden">' +
      // left menu sidebar
      '<nav class="d-flex flex-column flex-shrink-0 border-end border-secondary-subtle" style="width:200px;background:var(--bs-body-bg)">' +
        '<div class="p-3 border-bottom border-secondary-subtle">' +
          '<span class="text-uppercase text-secondary" style="font-size:11px;letter-spacing:1px">设置</span>' +
        '</div>' +
        '<div class="flex-grow-1 overflow-auto py-2">' +
          menuItems.map(m =>
            '<div class="ve-setting-menu-item px-3 py-2 cursor-pointer d-flex align-items-center gap-2' +
              (currentSettingTab === m.id ? ' active text-body bg-body-tertiary border-start border-primary' : ' text-secondary') + '"' +
              ' onclick="switchSettingTab(\'' + m.id + '\')">' +
              '<i class="bi bi-' + m.icon + '"></i>' +
              '<span class="small">' + m.label + '</span>' +
            '</div>'
          ).join('') +
        '</div>' +
      '</nav>' +
      // content area
      '<div class="flex-grow-1 overflow-auto p-4" id="veSettingContent">' +
        renderContent(currentSettingTab) +
      '</div>' +
    '</div>' +

    // status bar
    '<div class="d-flex align-items-center gap-3 px-3 flex-shrink-0 text-white small" style="height:24px;background-color:#0d6efd">' +
      '<span class="ms-auto">VanillaEditor v0.1.3</span>' +
      '<span id="veClock">' + new Date().toLocaleTimeString() + '</span>' +
    '</div>';

  // init offcanvas
  const sc = document.getElementById('veSettingsMenuClose');
  const st = document.getElementById('veSettingsToggler');
  if (sc) sc.addEventListener('click', closeSettingsMenu);
  if (st) st.addEventListener('click', () => { const el = document.getElementById('veSettingsMenuOffcanvas'); if (!el.classList.contains('show')) el.classList.add('show'); });
  document.addEventListener('click', e => {
    if (!e.target.closest('#veSettingsMenuOffcanvas') && !e.target.closest('#veSettingsToggler')) {
      closeSettingsMenu();
    }
  });
  // lazy load remote list for network tab
  if (currentSettingTab === 'network') {
    loadRemoteListIntoSetting();
    loadAccessControl();
  }
}

function switchSettingTab(tab) {
  currentSettingTab = tab;
  const items = document.querySelectorAll('.ve-setting-menu-item');
  const menuIds = ['account', 'network', 'version', 'about'];
  items.forEach((el, i) => {
    const isActive = menuIds[i] === tab;
    el.className = 've-setting-menu-item px-3 py-2 cursor-pointer d-flex align-items-center gap-2' +
      (isActive ? ' active text-body bg-body-tertiary border-start border-primary' : ' text-secondary');
  });
  const content = document.getElementById('veSettingContent');
  if (content) content.innerHTML = renderSettingContent(tab);
  if (tab === 'network') {
    loadRemoteListIntoSetting();
    loadAccessControl();
  }
}

function renderSettingContent(tab) {
  // account
  if (tab === 'account') {
    return '<div class="card h-100" style="max-width:500px">' +
      '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-person-badge me-1"></i>账号信息</div>' +
      '<div class="card-body">' +
        '<div class="d-flex align-items-center mb-4">' +
          '<i class="bi bi-person-circle fs-1 me-3 text-secondary"></i>' +
          '<div>' +
            '<div class="fw-semibold fs-5">' + esc(auth.username) + '</div>' +
            '<div class="text-secondary small">本地账号，数据存储于 data/' + esc(auth.username) + '/</div>' +
          '</div>' +
        '</div>' +
        '<button class="btn btn-outline-danger w-100" onclick="logout()"><i class="bi bi-box-arrow-right me-1"></i>退出登录</button>' +
      '</div>' +
    '</div>';
  }
  // network
  if (tab === 'network') {
    return '<div class="card h-100" style="max-width:500px">' +
      '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-shield-lock me-1"></i>远程访问控制</div>' +
      '<div class="card-body" id="veAccessControlBody"></div>' +
      '<div class="card-header bg-transparent border-secondary-subtle mt-3"><i class="bi bi-hdd-network me-1"></i>同步远端设备</div>' +
      '<div class="card-body">' +
        '<p class="text-secondary small mb-2">将其他设备的 VE 地址添加为 Git 远端，即可端到端同步。当前作用文档：' +
          (editor.activeDocId ? '<span class="badge text-bg-secondary ms-1">' + esc(editor.activeDocId) + '</span>' : '<span class="text-warning ms-1">未选择</span>') +
        '</p>' +
        '<div class="input-group mb-3">' +
          '<input id="newRemoteUrl" class="form-control" placeholder="http://192.168.1.x:5000">' +
          '<button class="btn btn-primary" onclick="addRemote()"><i class="bi bi-plus-lg"></i></button>' +
        '</div>' +
        '<div id="veRemoteListBody"></div>' +
      '</div>' +
    '</div>';
  }
  // version
  if (tab === 'version') {
    return '<div class="card h-100" style="max-width:500px">' +
      '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-git me-1"></i>Git 版本管理</div>' +
      '<div class="card-body">' +
        '<p class="text-secondary small mb-3">当前作用文档：' +
          (editor.activeDocId ? '<span class="badge text-bg-secondary ms-1">' + esc(editor.activeDocId) + '</span>' : '<span class="text-warning ms-1">未选择</span>') +
        '</p>' +
        '<div class="d-grid gap-2">' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuGitConfig()"><i class="bi bi-person-vcard me-2"></i>设置 Git 基础信息</button>' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuRemotes()"><i class="bi bi-hdd-network me-2"></i>配置远程仓库</button>' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuNewBranch()"><i class="bi bi-plus-square me-2"></i>添加新分支</button>' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuSwitchBranch()"><i class="bi bi-arrow-left-right me-2"></i>切换分支</button>' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuMergeBranch()"><i class="bi bi-sign-merge-left me-2"></i>合并分支</button>' +
          '<button class="btn btn-outline-secondary text-start" onclick="menuReset()"><i class="bi bi-arrow-counterclockwise me-2"></i>回退版本</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }
  // about
  if (tab === 'about') {
    return '<div class="card h-100" style="max-width:500px">' +
      '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-info-circle me-1"></i>关于</div>' +
      '<div class="card-body">' +
        '<div class="d-flex align-items-center mb-3">' +
          '<i class="bi bi-journal-richtext fs-1 me-3" style="color:var(--ve-accent)"></i>' +
          '<div>' +
            '<div class="fw-semibold fs-5" style="color:var(--ve-accent)">VanillaEditor</div>' +
            '<div class="text-secondary small">v0.1.0 — 分布式离线 Markdown 编辑器</div>' +
          '</div>' +
        '</div>' +
        '<p class="text-secondary small">每台设备独立运行，数据完全存储在本地，通过 Git 协议实现设备间端到端同步，无需任何第三方服务器。</p>' +
        '<hr class="border-secondary-subtle">' +
        '<div class="text-secondary small">' +
          '<div><i class="bi bi-check2 me-1"></i>完全离线可用</div>' +
          '<div><i class="bi bi-check2 me-1"></i>端到端 Git 同步</div>' +
          '<div><i class="bi bi-check2 me-1"></i>版本回溯与分支管理</div>' +
          '<div><i class="bi bi-check2 me-1"></i>工作区支持（本地目录直接打开）</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }
  return '';
}

async function loadRemoteListIntoSetting() {
  const body = document.getElementById('veRemoteListBody');
  if (!body) return;
  let remoteList = [];
  if (editor.activeDocId) {
    try { const r = await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) }); if (r) remoteList = r; } catch (e) {}
  }
  body.innerHTML = remoteList.length === 0
    ? '<div class="text-secondary small">暂无远端设备</div>'
    : remoteList.map(r =>
        '<div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary-subtle small">' +
          '<i class="bi bi-router text-secondary"></i>' +
          '<span class="flex-grow-1 text-truncate">' + esc(r.name) + '</span>' +
          '<span class="text-secondary text-truncate" style="max-width:45%">' + esc(r.url) + '</span>' +
          '<button class="btn btn-sm btn-outline-danger py-0" title="移除" onclick="removeRemote(\'' + esc(r.name) + '\')"><i class="bi bi-x-lg"></i></button>' +
        '</div>').join('');
}

async function loadAccessControl() {
  const body = document.getElementById('veAccessControlBody');
  if (!body) return;
  try {
    const data = await apiFetch('/access/status');
    if (!data) return;
    const enabled = data.enabled;
    body.innerHTML =
      '<div class="d-flex align-items-center justify-content-between mb-3">' +
        '<div>' +
          '<div class="fw-semibold">远程访问</div>' +
          '<div class="text-secondary small">允许局域网内其他设备通过浏览器访问本机的 VE</div>' +
        '</div>' +
        '<div class="form-check form-switch mb-0">' +
          '<input class="form-check-input" type="checkbox" role="switch" id="veAccessToggle" ' + (enabled ? 'checked' : '') + ' onchange="toggleAccess(this.checked)">' +
        '</div>' +
      '</div>' +
      (enabled ?
        '<div class="alert alert-info py-2 small mb-3">' +
          '<div><i class="bi bi-link-45deg me-1"></i>访问地址：<strong>' + esc(data.url) + '</strong></div>' +
          '<div class="mt-1"><i class="bi bi-key me-1"></i>访问码：<strong class="font-monospace">' + esc(data.access_code) + '</strong> <button class="btn btn-sm py-0 ms-1" onclick="copyAccessCode(\'' + esc(data.access_code) + '\')"><i class="bi bi-clipboard"></i></button></div>' +
          '<div class="mt-1 text-secondary">将此地址和访问码发给局域网内的其他设备，在登录页输入即可远程访问</div>' +
        '</div>' :
        '<div class="text-secondary small">关闭远程访问后，其他设备无法通过浏览器访问本机</div>');
  } catch (e) {
    body.innerHTML = '<div class="text-danger small">加载失败</div>';
  }
}

async function toggleAccess(enabled) {
  try {
    if (enabled) {
      const r = await apiFetch('/access/enable', { method: 'POST', body: '{}' });
      if (r) toast('远程访问已开启', 'ok');
    } else {
      await apiFetch('/access/disable', { method: 'POST', body: '{}' });
      toast('远程访问已关闭', 'info');
    }
    loadAccessControl();
  } catch (e) {
    toast('操作失败', 'err');
    loadAccessControl();
  }
}

function copyAccessCode(code) {
  navigator.clipboard.writeText(code).then(() => toast('访问码已复制', 'ok')).catch(() => toast('复制失败', 'err'));
}

function closeSettingsMenu() {
  const el = document.getElementById('veSettingsMenuOffcanvas');
  if (el) el.classList.remove('show');
  document.querySelector('.offcanvas-backdrop')?.remove();
  document.body.classList.remove('modal-open');
}

// ── Routes ───────────────────────────────────────────────────
Router.register('#/login', () => {
  if (auth.isLoggedIn) { Router.go('#/editor'); return; }
  renderLogin();
});
Router.register('#/editor', async () => {
  if (!auth.isLoggedIn) { Router.go('#/login'); return; }
  renderEditor();
  await Promise.all([loadFiles(), loadWorkspaces()]);
  if (editor.activeFilePath) renderEditor();
});
Router.register('#/setting', async () => {
  if (!auth.isLoggedIn) { Router.go('#/login'); return; }
  await renderSetting();
});

// ── Init ─────────────────────────────────────────────────────
window.addEventListener('error', e => console.error('[VE Error]', e.message));
if (!location.hash) location.hash = auth.isLoggedIn ? '#/editor' : '#/login';
Router.render();

window.addEventListener('resize', () => {
  if (location.hash === '#/editor') applyMobilePreviewState();
});
