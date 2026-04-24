// ─── 状态 ──────────────────────────────────────────────────────────────────────
let currentEmailId = null;
let currentEmailAddr = '';
let currentMessageId = null;
let currentMessages = [];
let autoRefreshTimer = null;
let inboxLoading = false;

const LAST_EMAIL_KEY = 'tempmail:last-address';

// ─── HTTP ──────────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
    const resp = await fetch(path, {
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });

    if (resp.status === 401) {
        showLogin();
        throw new Error('未授权');
    }

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.error || `HTTP ${resp.status}`);
    }

    return data;
}

function toast(msg, type = 'info') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'fixed right-6 top-6 z-50 rounded-2xl px-4 py-3 text-sm text-white shadow-lg';
    el.classList.add(type === 'error' ? 'bg-red-500' : type === 'success' ? 'bg-brand-500' : 'bg-slate-900');
    el.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.add('hidden'), 2500);
}

function escapeHtml(value) {
    if (value == null) return '';
    return String(value).replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));
}

function normalizeEmailAddress(value) {
    return String(value || '').trim().toLowerCase();
}

function formatDate(value) {
    if (!value) return '';
    const date = typeof value === 'number' ? new Date(value) : new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('zh-CN', { hour12: false });
}

function formatRelative(value) {
    if (!value) return '';
    const date = typeof value === 'number' ? new Date(value) : new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);

    const diff = Date.now() - date.getTime();
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return `${Math.floor(diff / 86400000)} 天前`;
}

function setSearchError(message = '') {
    const errorEl = document.getElementById('searchError');
    if (message) {
        errorEl.textContent = message;
        errorEl.classList.remove('hidden');
        return;
    }
    errorEl.textContent = '';
    errorEl.classList.add('hidden');
}

function syncRefreshButton() {
    const button = document.getElementById('refreshMessagesBtn');
    if (!button) return;
    button.disabled = inboxLoading || !currentEmailAddr;
}

function setSearchBusy(isBusy) {
    const submitBtn = document.getElementById('searchSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = isBusy;
        submitBtn.textContent = isBusy ? '提取中...' : '提取邮件';
    }
    syncRefreshButton();
}

function renderMessageListState(title, description = '', tone = 'neutral') {
    const listEl = document.getElementById('messageList');
    const titleClass = tone === 'error' ? 'text-red-500' : 'text-slate-500';
    const descClass = tone === 'error' ? 'text-red-400' : 'text-slate-400';
    listEl.innerHTML = `
        <div class="px-6 py-14 text-center">
            <p class="text-sm font-medium ${titleClass}">${escapeHtml(title)}</p>
            ${description ? `<p class="mt-2 text-xs leading-5 ${descClass}">${escapeHtml(description)}</p>` : ''}
        </div>`;
}

function renderDetailPlaceholder(message, tone = 'neutral') {
    const detailEl = document.getElementById('messageDetail');
    const iconClass = tone === 'error' ? 'text-red-200' : 'text-slate-200';
    const textClass = tone === 'error' ? 'text-red-500' : 'text-slate-400';
    const borderClass = tone === 'error' ? 'border-red-100 bg-red-50/70' : 'border-slate-200 bg-white/85';

    detailEl.innerHTML = `
        <div class="rounded-[28px] border border-dashed ${borderClass} px-6 py-16 text-center ${textClass}">
            <svg class="mx-auto mb-4 h-16 w-16 ${iconClass}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
            <p class="text-sm">${escapeHtml(message)}</p>
        </div>`;
}

function resetInboxState() {
    currentEmailId = null;
    currentEmailAddr = '';
    currentMessageId = null;
    currentMessages = [];

    document.getElementById('selectedEmailAddr').textContent = '未选择邮箱';
    document.getElementById('inboxHint').textContent = '输入邮箱后即可开始提取。';
    document.getElementById('messageTotal').textContent = '尚未查询';
    syncRefreshButton();
    renderMessageListState('输入邮箱后提取邮件');
    renderDetailPlaceholder('提取邮件后，点击左侧任意一封邮件查看详情。');
}

function rememberLastEmailAddress(address) {
    try {
        if (address) {
            window.localStorage.setItem(LAST_EMAIL_KEY, address);
        }
    } catch {
        // ignore storage failures
    }
}

function restoreLastEmailAddress() {
    try {
        const lastEmail = window.localStorage.getItem(LAST_EMAIL_KEY);
        if (lastEmail) {
            document.getElementById('targetEmailInput').value = lastEmail;
        }
    } catch {
        // ignore storage failures
    }
}

function renderMessageList() {
    if (!currentMessages.length) {
        renderMessageListState('当前邮箱暂无邮件', '你可以稍后点击刷新，或打开自动刷新等待新邮件。');
        return;
    }

    const listEl = document.getElementById('messageList');
    listEl.innerHTML = currentMessages.map((message) => `
        <button type="button" onclick="selectMessage('${message.id}')"
                class="message-item block w-full border-b border-slate-100 px-5 py-4 text-left transition hover:bg-slate-50 ${message.id === currentMessageId ? 'bg-brand-500/5 ring-1 ring-inset ring-brand-500/20' : 'bg-white'}">
            <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-slate-900">${escapeHtml(message.subject || '(无主题)')}</p>
                    <p class="mt-1 truncate text-xs text-slate-500">${escapeHtml(message.from_address || '(未知发件人)')}</p>
                </div>
                <span class="shrink-0 text-xs text-slate-400">${escapeHtml(formatRelative(message.received_at))}</span>
            </div>
        </button>`).join('');
}

// ─── 登录 ──────────────────────────────────────────────────────────────────────
function showLogin() {
    document.getElementById('loginView').classList.remove('hidden');
    document.getElementById('mainView').classList.add('hidden');
    stopAutoRefresh();
}

function showMain() {
    document.getElementById('loginView').classList.add('hidden');
    document.getElementById('mainView').classList.remove('hidden');

    restoreLastEmailAddress();
    resetInboxState();

    const input = document.getElementById('targetEmailInput');
    if (input.value.trim()) {
        loadInbox(false);
    }
}

document.getElementById('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const password = document.getElementById('passwordInput').value;
    const errorEl = document.getElementById('loginError');
    errorEl.classList.add('hidden');

    try {
        await api('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ password }),
        });
        showMain();
    } catch (error) {
        errorEl.textContent = error.message || '登录失败';
        errorEl.classList.remove('hidden');
    }
});

async function logout() {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
    showLogin();
}

// ─── 收件箱提取 ────────────────────────────────────────────────────────────────
async function loadInbox(showToast = false, addressOverride = null) {
    if (inboxLoading) return;

    const input = document.getElementById('targetEmailInput');
    const address = String(addressOverride || input.value).trim();

    setSearchError('');
    if (!address) {
        resetInboxState();
        setSearchError('请输入邮箱地址');
        return;
    }

    if (!address.includes('@')) {
        resetInboxState();
        setSearchError('请输入正确的邮箱地址');
        return;
    }

    inboxLoading = true;
    setSearchBusy(true);

    const listEl = document.getElementById('messageList');
    const previousAddress = normalizeEmailAddress(currentEmailAddr);
    const previousMessageId = currentMessageId;

    document.getElementById('selectedEmailAddr').textContent = address;
    document.getElementById('inboxHint').textContent = '正在提取该邮箱下的全部邮件...';
    document.getElementById('messageTotal').textContent = '同步中...';
    listEl.innerHTML = '<div class="px-6 py-14 text-center text-sm text-slate-400">正在提取邮件，请稍候...</div>';

    try {
        const params = new URLSearchParams({ address });
        const data = await api(`/api/inbox/messages?${params.toString()}`);
        const resolvedAddress = data.address || address;
        const messages = Array.isArray(data.messages) ? data.messages : [];
        const sameInbox = normalizeEmailAddress(resolvedAddress) === previousAddress;

        currentEmailId = data.emailId || null;
        currentEmailAddr = resolvedAddress;
        currentMessages = messages;
        currentMessageId = sameInbox && messages.some((message) => message.id === previousMessageId)
            ? previousMessageId
            : null;

        input.value = resolvedAddress;
        rememberLastEmailAddress(resolvedAddress);

        document.getElementById('selectedEmailAddr').textContent = resolvedAddress;
        document.getElementById('inboxHint').textContent = messages.length
            ? '已同步完成，可继续刷新或开启自动刷新。'
            : '邮箱已匹配成功，但当前没有邮件。';
        document.getElementById('messageTotal').textContent = `共 ${data.total != null ? data.total : messages.length} 封邮件`;

        renderMessageList();

        if (!currentMessageId) {
            renderDetailPlaceholder(messages.length
                ? '从左侧选择一封邮件查看详情。'
                : '当前邮箱暂无邮件。');
        }

        if (showToast) {
            toast(messages.length ? `提取完成，共 ${messages.length} 封邮件` : '提取完成，当前暂无邮件', 'success');
        }
    } catch (error) {
        resetInboxState();
        stopAutoRefresh();
        setSearchError(error.message || '提取失败');

        document.getElementById('selectedEmailAddr').textContent = address || '未选择邮箱';
        document.getElementById('inboxHint').textContent = '请确认邮箱属于当前账户，或稍后重试。';
        document.getElementById('messageTotal').textContent = '查询失败';

        renderMessageListState(error.message || '提取失败', '请检查邮箱是否存在于当前账户下。', 'error');
        renderDetailPlaceholder('当前无法展示邮件详情，请修正邮箱后重试。', 'error');

        if (showToast) {
            toast(`提取失败: ${error.message || '未知错误'}`, 'error');
        }
    } finally {
        inboxLoading = false;
        setSearchBusy(false);
    }
}

document.getElementById('searchForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    await loadInbox(true);
});

document.getElementById('targetEmailInput').addEventListener('input', () => {
    setSearchError('');
});

// ─── 邮件详情 ──────────────────────────────────────────────────────────────────
async function selectMessage(messageId) {
    if (!currentEmailId) return;

    currentMessageId = messageId;
    renderMessageList();

    const detailEl = document.getElementById('messageDetail');
    detailEl.innerHTML = '<div class="px-2 py-16 text-center text-sm text-slate-400">正在加载邮件详情...</div>';

    try {
        const data = await api(`/api/emails/${currentEmailId}/messages/${messageId}`);
        const message = data.message || {};
        const hasHtml = Boolean(message.html && message.html.trim());
        const hasContent = Boolean(message.content && message.content.trim());
        const defaultView = hasHtml ? 'html' : hasContent ? 'text' : 'raw';

        detailEl.innerHTML = `
            <div class="mx-auto max-w-4xl">
                <div class="mb-6 rounded-[28px] border border-slate-200 bg-white/95 p-6 shadow-sm">
                    <p class="text-xs font-semibold uppercase tracking-[0.24em] text-brand-600/80">Message</p>
                    <h2 class="mt-3 break-words text-2xl font-semibold text-slate-950">${escapeHtml(message.subject || '(无主题)')}</h2>
                    <div class="mt-5 grid gap-3 text-sm sm:grid-cols-3">
                        <div class="rounded-2xl bg-slate-50 px-4 py-3">
                            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">发件人</p>
                            <p class="mt-2 break-all text-slate-900">${escapeHtml(message.from_address || '(未知发件人)')}</p>
                        </div>
                        <div class="rounded-2xl bg-slate-50 px-4 py-3">
                            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">收件箱</p>
                            <p class="mt-2 break-all text-slate-900">${escapeHtml(currentEmailAddr)}</p>
                        </div>
                        <div class="rounded-2xl bg-slate-50 px-4 py-3">
                            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">接收时间</p>
                            <p class="mt-2 text-slate-900">${escapeHtml(formatDate(message.received_at))}</p>
                        </div>
                    </div>
                </div>

                <div class="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
                    <div class="flex flex-wrap items-center gap-1 border-b border-slate-200 bg-slate-50 px-3 py-2">
                        ${hasHtml ? `<button type="button" onclick="switchView('html')" id="tabHtml" class="tab-btn rounded-2xl px-3 py-2 text-sm font-medium ${defaultView === 'html' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}">HTML</button>` : ''}
                        ${hasContent ? `<button type="button" onclick="switchView('text')" id="tabText" class="tab-btn rounded-2xl px-3 py-2 text-sm font-medium ${defaultView === 'text' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}">纯文本</button>` : ''}
                        <button type="button" onclick="switchView('raw')" id="tabRaw" class="tab-btn rounded-2xl px-3 py-2 text-sm font-medium ${defaultView === 'raw' ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}">原始</button>
                    </div>
                    <div id="viewHtml" class="${defaultView === 'html' ? '' : 'hidden'}">
                        <iframe class="email-html-frame" sandbox="allow-same-origin" srcdoc="${escapeHtml(message.html || '')}"></iframe>
                    </div>
                    <div id="viewText" class="${defaultView === 'text' ? '' : 'hidden'} p-6">
                        <pre class="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-800">${escapeHtml(message.content || '(无纯文本内容)')}</pre>
                    </div>
                    <div id="viewRaw" class="${defaultView === 'raw' ? '' : 'hidden'} p-6">
                        <pre class="whitespace-pre-wrap break-all rounded-3xl bg-slate-50 p-4 text-xs leading-6 text-slate-600">${escapeHtml(JSON.stringify(message, null, 2))}</pre>
                    </div>
                </div>
            </div>`;
    } catch (error) {
        detailEl.innerHTML = `<div class="rounded-[28px] border border-red-100 bg-red-50/70 px-6 py-16 text-center text-sm text-red-500">加载失败: ${escapeHtml(error.message || '未知错误')}</div>`;
    }
}

function switchView(view) {
    ['Html', 'Text', 'Raw'].forEach((name) => {
        const tab = document.getElementById(`tab${name}`);
        const pane = document.getElementById(`view${name}`);
        if (!tab || !pane) return;

        if (name.toLowerCase() === view) {
            tab.classList.add('bg-white', 'text-brand-600', 'shadow-sm');
            tab.classList.remove('text-slate-500');
            pane.classList.remove('hidden');
        } else {
            tab.classList.remove('bg-white', 'text-brand-600', 'shadow-sm');
            tab.classList.add('text-slate-500');
            pane.classList.add('hidden');
        }
    });
}

function refreshCurrentInbox() {
    if (!currentEmailAddr) return;
    loadInbox(true, currentEmailAddr);
}

// ─── 自动刷新 ──────────────────────────────────────────────────────────────────
document.getElementById('autoRefresh').addEventListener('change', (event) => {
    if (event.target.checked) {
        startAutoRefresh();
    } else {
        stopAutoRefresh(false);
    }
});

function startAutoRefresh() {
    if (!currentEmailAddr) {
        document.getElementById('autoRefresh').checked = false;
        toast('请先成功提取一个邮箱的邮件', 'error');
        return;
    }

    stopAutoRefresh(false);
    autoRefreshTimer = setInterval(() => {
        if (currentEmailAddr) {
            loadInbox(false, currentEmailAddr);
        }
    }, 10000);
}

function stopAutoRefresh(resetCheckbox = true) {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }

    if (resetCheckbox) {
        const checkbox = document.getElementById('autoRefresh');
        if (checkbox) checkbox.checked = false;
    }
}

// ─── 初始化 ────────────────────────────────────────────────────────────────────
(async function init() {
    try {
        const { authenticated } = await api('/api/auth/check');
        if (authenticated) {
            showMain();
        } else {
            showLogin();
        }
    } catch {
        showLogin();
    }
})();
