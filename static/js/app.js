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
let expandedDocs = {};
let commitMsg = '';
let remotes = [];
let commits = [];
let isRegister = false;
let loginError = '';
let saveTimer = null;
let fontSize = parseInt(localStorage.getItem('ve_font_size') || '14', 10);
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

// ── Markdown parser (simple inline) ──────────────────────────
function parseMd(src) {
  if (!src) return '';
  return src
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
    .replace(/\*(.*)\*/gim, '<em>$1</em>')
    .replace(/`([^`]+)`/gim, '<code>$1</code>')
    .replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>')
    .replace(/^\- (.*$)/gim, '<li>$1</li>')
    .replace(/^\d+\. (.*$)/gim, '<li>$1</li>')
    .replace(/\n/gim, '<br>');
}

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
async function loadFiles() {
  const data = await apiFetch('/docs');
  if (!data) return;
  sidebarDocs = data;
  if (data.length > 0 && !editor.activeDocId) {
    const first = data[0];
    editor.activeDocId = first.id;
    if (first.children && first.children.length > 0) await openFile(first.id, first.children[0].path);
  }
}

async function openFile(docId, filePath) {
  editor.activeDocId = docId;
  editor.activeFilePath = filePath;
  const r = await apiFetch('/files/' + docId + '/' + encodeURIComponent(filePath));
  if (r) {
    editor.content = r.content;
    editor.fileSha = r.sha;
    editor.unsaved = false;
  }
  if (location.hash !== '#/editor') { Router.go('#/editor'); return; }
  renderEditor();
}

function onEditorChange(val) {
  editor.content = val;
  editor.unsaved = true;
  const pv = document.getElementById('vePreview');
  if (pv) pv.innerHTML = parseMd(val);
  document.querySelectorAll('.ve-unsaved-dot').forEach(el => el.classList.remove('hidden'));
  const ub = document.getElementById('veUnsavedBar');
  if (ub) ub.classList.remove('hidden');
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    if (!editor.activeDocId || !editor.activeFilePath) return;
    const r = await apiFetch('/files/' + editor.activeDocId + '/' + encodeURIComponent(editor.activeFilePath), {
      method: 'PUT', body: JSON.stringify({ content: val })
    });
    if (r) {
      editor.unsaved = false;
      document.querySelectorAll('.ve-unsaved-dot').forEach(el => el.classList.add('hidden'));
      const ub = document.getElementById('veUnsavedBar');
      if (ub) ub.classList.add('hidden');
      toast('已保存', 'ok');
    }
  }, 1500);
}

async function createDoc() {
  const name = prompt('新建文档名称（如：notes.md）：');
  if (!name) return;
  const r = await apiFetch('/docs', { method: 'POST', body: JSON.stringify({ name: name, content: '' }) });
  if (r) {
    editor.activeDocId = r.id;
    await loadFiles();
    renderEditor();
  }
}

async function deleteDoc(docId) {
  if (!confirm('确定删除文档「' + docId + '」？其 Git 历史将一并删除。')) return;
  await apiFetch('/docs/' + encodeURIComponent(docId), { method: 'DELETE' });
  if (editor.activeDocId === docId) {
    editor.activeDocId = ''; editor.activeFilePath = ''; editor.content = '';
  }
  await loadFiles();
  renderEditor();
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
  activePanel = activePanel === panel ? 'files' : panel;
  renderEditor();
  const el = document.getElementById('veSidebar');
  if (el && window.innerWidth < 992) {
    const oc = bootstrap.Offcanvas.getInstance(el) || new bootstrap.Offcanvas(el);
    oc.show();
  }
}

function toggleDoc(docId) {
  expandedDocs[docId] = !expandedDocs[docId];
  renderEditor();
}

function logout() {
  auth.logout();
  Router.go('#/login');
}

function onFontSizeChange(val) {
  fontSize = parseInt(val, 10);
  localStorage.setItem('ve_font_size', String(fontSize));
  document.documentElement.style.setProperty('--ed-font-size', fontSize + 'px');
}

// ── Editor page ──────────────────────────────────────────────
function renderEditor() {
  const app = document.getElementById('app');
  const fileName = editor.activeFilePath ? editor.activeFilePath.split('/').pop() : '';

  const filesPanel =
    '<div class="d-flex justify-content-between align-items-center px-3 py-2 border-bottom border-secondary-subtle">' +
      '<span class="text-uppercase text-secondary" style="font-size:11px;letter-spacing:1px">资源管理器</span>' +
      '<span>' +
        '<button class="btn btn-sm btn-outline-secondary me-1" title="新建文档" onclick="createDoc()"><i class="bi bi-plus-lg"></i></button>' +
        (editor.activeDocId ? '<button class="btn btn-sm btn-outline-danger" title="删除当前文档" onclick="deleteDoc(editor.activeDocId)"><i class="bi bi-trash3"></i></button>' : '') +
      '</span>' +
    '</div>' +
    '<div class="ve-scroll py-1">' +
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
        '<a class="navbar-brand ve-brand mb-0" href="#/editor"><i class="bi bi-journal-richtext me-1"></i>VE</a>' +
        '<button class="navbar-toggler border-0 shadow-none" type="button" data-bs-toggle="offcanvas" data-bs-target="#veSidebar" aria-controls="veSidebar" aria-label="打开侧边栏">' +
          '<i class="bi bi-layout-sidebar"></i>' +
        '</button>' +
        '<button class="navbar-toggler border-0 shadow-none" type="button" data-bs-toggle="collapse" data-bs-target="#veNav" aria-controls="veNav" aria-label="打开菜单">' +
          '<i class="bi bi-list"></i>' +
        '</button>' +
        '<div class="collapse navbar-collapse" id="veNav">' +
          '<ul class="navbar-nav me-auto">' +
            '<li class="nav-item"><a class="nav-link' + (activePanel === 'files' ? ' active' : '') + '" href="#" onclick="setPanel(\'files\');return false"><i class="bi bi-folder2 me-1"></i>文件</a></li>' +
            '<li class="nav-item"><a class="nav-link' + (activePanel === 'git' ? ' active' : '') + '" href="#" onclick="setPanel(\'git\');return false"><i class="bi bi-git me-1"></i>Git</a></li>' +
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

    '<div class="d-flex flex-grow-1 overflow-hidden">' +
      // sidebar (offcanvas below lg)
      '<aside class="offcanvas-lg offcanvas-start border-end border-secondary-subtle ve-sidebar" tabindex="-1" id="veSidebar" aria-labelledby="veSidebarLabel">' +
        '<div class="offcanvas-header d-lg-none py-1 border-bottom border-secondary-subtle">' +
          '<span class="text-uppercase text-secondary" id="veSidebarLabel" style="font-size:11px">' + (activePanel === 'git' ? 'Git' : '资源管理器') + '</span>' +
          '<button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="关闭"></button>' +
        '</div>' +
        '<div class="offcanvas-body d-flex p-0">' +
          '<div class="ve-abar d-none d-lg-flex">' +
            '<div class="ib' + (activePanel === 'files' ? ' on' : '') + '" title="资源管理器" onclick="setPanel(\'files\')"><i class="bi bi-files"></i></div>' +
            '<div class="ib' + (activePanel === 'git' ? ' on' : '') + '" title="Git 版本管理" onclick="setPanel(\'git\')"><i class="bi bi-git"></i></div>' +
          '</div>' +
          '<div class="panel">' + (activePanel === 'git' ? gitPanel : filesPanel) + '</div>' +
        '</div>' +
      '</aside>' +

      // main area
      '<main class="flex-grow-1 d-flex flex-column overflow-hidden">' +
        '<div class="d-flex align-items-center gap-2 px-3 py-1 bg-body-tertiary border-bottom border-secondary-subtle flex-shrink-0">' +
          '<button class="btn btn-sm btn-outline-secondary py-0 d-lg-none" onclick="setPanel(\'files\')" title="文件列表"><i class="bi bi-list"></i></button>' +
          '<button class="btn btn-sm btn-outline-secondary py-0 d-lg-none" onclick="setPanel(\'git\')" title="Git 面板"><i class="bi bi-git"></i></button>' +
          (fileName ?
            '<span class="d-flex align-items-center gap-2 ms-2 px-2 py-1 rounded bg-body border border-secondary-subtle small">' +
              '<i class="bi bi-file-earmark-text"></i>' + esc(fileName) +
              '<span class="ve-unsaved-dot' + (editor.unsaved ? '' : ' hidden') + '" title="未保存"></span>' +
            '</span>' : '<span class="text-secondary small ms-2">未打开文件</span>') +
        '</div>' +

        '<div class="ve-split">' +
          '<div class="pane d-flex flex-column">' +
            '<textarea class="ve-editor" id="veEditor" spellcheck="false" placeholder="在此输入 Markdown...">' + esc(editor.content) + '</textarea>' +
          '</div>' +
          '<div class="pane ve-preview" id="vePreview">' + parseMd(editor.content || '') + '</div>' +
        '</div>' +
      '</main>' +
    '</div>' +

    // status bar
    '<div class="d-flex align-items-center gap-3 px-3 flex-shrink-0 text-white small" style="height:24px;background:var(--bs-primary-bg-subtle);background-color:#0d6efd">' +
      '<span><i class="bi bi-diagram-3 me-1"></i>' + esc(editor.gitBranch || 'main') + '</span>' +
      (editor.fileSha ? '<span><i class="bi bi-hash me-1"></i>' + esc(editor.fileSha.slice(0, 7)) + '</span>' : '') +
      '<span class="d-flex align-items-center' + (editor.unsaved ? '' : ' hidden') + '" id="veUnsavedBar"><span class="ve-unsaved-dot me-1"></span>有未保存更改</span>' +
      '<span class="ms-auto">VanillaEditor v0.1.0</span>' +
      '<span id="veClock">' + new Date().toLocaleTimeString() + '</span>' +
    '</div>';

  const ta = document.getElementById('veEditor');
  if (ta) ta.addEventListener('input', e => onEditorChange(e.target.value));
  if (activePanel === 'git') loadGitData();
}

// ── Settings page ────────────────────────────────────────────
async function renderSetting() {
  const app = document.getElementById('app');
  let me = null;
  try { me = await apiFetch('/auth/me'); } catch (e) {}
  if (!me) return;

  // 若已打开文档，加载其远端列表
  let remoteList = [];
  if (editor.activeDocId) {
    try { const r = await apiFetch('/sync/remote', { method: 'POST', body: JSON.stringify({ doc_id: editor.activeDocId }) }); if (r) remoteList = r; } catch (e) {}
  }

  app.innerHTML =
    '<nav class="navbar navbar-expand-lg bg-body-tertiary border-bottom border-secondary-subtle px-2 py-1 flex-shrink-0">' +
      '<div class="container-fluid">' +
        '<a class="navbar-brand ve-brand mb-0" href="#/editor"><i class="bi bi-journal-richtext me-1"></i>VE</a>' +
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
    '</nav>' +

    '<div class="container-fluid py-4 overflow-auto flex-grow-1">' +
      '<div class="row justify-content-center g-3">' +
        // 用户信息
        '<div class="col-12 col-md-6 col-xl-4">' +
          '<div class="card h-100">' +
            '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-person-badge me-1"></i>用户信息</div>' +
            '<div class="card-body">' +
              '<div class="d-flex align-items-center mb-3">' +
                '<i class="bi bi-person-circle fs-1 me-3 text-secondary"></i>' +
                '<div>' +
                  '<div class="fw-semibold">' + esc(me.username) + '</div>' +
                  '<div class="text-secondary small">本地账号，数据存储于 data/' + esc(me.username) + '/</div>' +
                '</div>' +
              '</div>' +
              '<button class="btn btn-outline-danger w-100" onclick="logout()"><i class="bi bi-box-arrow-right me-1"></i>退出登录</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
        // 编辑器设置
        '<div class="col-12 col-md-6 col-xl-4">' +
          '<div class="card h-100">' +
            '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-sliders me-1"></i>编辑器</div>' +
            '<div class="card-body">' +
              '<label class="form-label small text-secondary" for="fsSelect">字体大小</label>' +
              '<select class="form-select mb-3" id="fsSelect" onchange="onFontSizeChange(this.value)">' +
                [12, 14, 16, 18, 20].map(s => '<option value="' + s + '"' + (s === fontSize ? ' selected' : '') + '>' + s + ' px</option>').join('') +
              '</select>' +
              '<div class="text-secondary small"><i class="bi bi-info-circle me-1"></i>设置自动保存在浏览器本地</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        // 远程设备 / 同步
        '<div class="col-12 col-xl-4">' +
          '<div class="card h-100">' +
            '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-hdd-network me-1"></i>远程设备（同步）</div>' +
            '<div class="card-body">' +
              '<p class="text-secondary small mb-2">将其他设备的 VE 地址添加为 Git 远端，即可端到端同步。当前作用文档：' +
                (editor.activeDocId ? '<span class="badge text-bg-secondary">' + esc(editor.activeDocId) + '</span>' : '<span class="text-warning">未选择</span>') +
              '</p>' +
              '<div class="input-group mb-3">' +
                '<input id="newRemoteUrl" class="form-control" placeholder="http://192.168.1.x:5000">' +
                '<button class="btn btn-primary" onclick="addRemote()"><i class="bi bi-plus-lg"></i></button>' +
              '</div>' +
              (remoteList.length === 0 ?
                '<div class="text-secondary small">暂无远端设备</div>' :
                remoteList.map(r =>
                  '<div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary-subtle small">' +
                    '<i class="bi bi-router text-secondary"></i>' +
                    '<span class="flex-grow-1 text-truncate">' + esc(r.name) + '</span>' +
                    '<span class="text-secondary text-truncate" style="max-width:45%">' + esc(r.url) + '</span>' +
                    '<button class="btn btn-sm btn-outline-danger py-0" title="移除" onclick="removeRemote(\'' + esc(r.name) + '\')"><i class="bi bi-x-lg"></i></button>' +
                  '</div>').join('')) +
            '</div>' +
          '</div>' +
        '</div>' +
        // 关于
        '<div class="col-12">' +
          '<div class="card">' +
            '<div class="card-header bg-transparent border-secondary-subtle"><i class="bi bi-info-circle me-1"></i>关于</div>' +
            '<div class="card-body text-secondary small">' +
              'VanillaEditor v0.1.0 — 分布式离线 Markdown 编辑器。数据完全存储在本地（data/ 目录），不上传任何第三方服务器；' +
              '文档以 Git 仓库形式保存，支持版本回溯与设备间端到端同步。' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>' +

    '<div class="d-flex align-items-center gap-3 px-3 flex-shrink-0 text-white small" style="height:24px;background-color:#0d6efd">' +
      '<span class="ms-auto">VanillaEditor v0.1.0</span>' +
      '<span id="veClock">' + new Date().toLocaleTimeString() + '</span>' +
    '</div>';
}

// ── Routes ───────────────────────────────────────────────────
Router.register('#/login', () => {
  if (auth.isLoggedIn) { Router.go('#/editor'); return; }
  renderLogin();
});
Router.register('#/editor', async () => {
  if (!auth.isLoggedIn) { Router.go('#/login'); return; }
  renderEditor();
  await loadFiles();
  if (editor.activeFilePath) renderEditor();
});
Router.register('#/setting', async () => {
  if (!auth.isLoggedIn) { Router.go('#/login'); return; }
  await renderSetting();
});

// ── Init ─────────────────────────────────────────────────────
if (!location.hash) location.hash = auth.isLoggedIn ? '#/editor' : '#/login';
Router.render();
