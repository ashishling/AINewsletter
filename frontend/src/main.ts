// @ts-nocheck
import "./styles/base.css";
import "./styles/curator.css";

declare global {
  interface Window {
    openAddArticle: () => void;
    openArchives: () => void;
    generateNewsletter: () => Promise<void>;
    archiveStatus: (status: string) => Promise<void>;
    archiveCurrentFolder: () => Promise<void>;
    pullFromFeeds: () => Promise<void>;
    viewNewsletter: (selectedWeek?: string | null) => Promise<void>;
    switchView: (viewName: string) => void;
    closeModal: () => void;
    closeArchives: () => void;
    closeAddArticle: () => void;
    closeReader: () => void;
    fetchMetadata: () => Promise<void>;
    submitArticle: (event: Event) => Promise<void>;
    loadNewsletterContent: (newsletterId: string) => Promise<void>;
    unarchiveArticle: (articleId: string) => Promise<void>;
    saveSubscriptionByEncoded: (encodedDomain: string, inputId: string) => void;
    removeSubscriptionByEncoded: (encodedDomain: string, deleteArticles: boolean) => void;
    setQueueStatus: (status: string) => void;
    onSubscriptionsSortChange: () => void;
    curate: (articleId: string, status: string) => Promise<void>;
    openReader: (articleId: string) => void;
    removeFeedForArticle: (articleId: string, deleteArticles?: boolean) => Promise<void>;
    toggleTopPick: (articleId: string, topPick: boolean) => Promise<void>;
  }
}
        let articles = { pending: [], shortlisted: [], rejected: [] };
        let subscriptions = [];
        let notesSaveTimeout = {};
        let notesStatusResetTimeout = null;
        let activeReaderArticleId = null;
        let activeView = 'articles';
        let activeQueueStatus = 'pending';
        const queueStatuses = ['pending', 'shortlisted', 'rejected'];
        let nextQueueIndexAfterMutation = null;
        const queueScrollTopByStatus = { pending: 0, shortlisted: 0, rejected: 0 };
        let subscriptionsSort = 'domain_asc';

        async function init() {
            await loadArticles();
            await loadSubscriptions();
        }

        async function loadArticles() {
            try {
                const response = await fetch('/api/articles');
                const data = await response.json();

                // Group by status
                articles = { pending: [], shortlisted: [], rejected: [] };
                data.articles.forEach(article => {
                    const status = article.status || 'pending';
                    if (articles[status]) {
                        articles[status].push(article);
                    }
                });

                renderQueue();
                syncReaderSelection();
                await loadStats();
            } catch (error) {
                showToast('Failed to load articles', 'error');
            }
        }

        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();

                document.getElementById('stat-total').textContent = stats.total;
                document.getElementById('stat-pending').textContent = stats.pending;
                document.getElementById('stat-shortlisted').textContent = stats.shortlisted;
                document.getElementById('stat-rejected').textContent = stats.rejected;
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }

        function switchView(viewName) {
            activeView = viewName;
            document.getElementById('tab-articles').classList.toggle('active', viewName === 'articles');
            document.getElementById('tab-subscriptions').classList.toggle('active', viewName === 'subscriptions');
            document.getElementById('articles-view').classList.toggle('active', viewName === 'articles');
            document.getElementById('subscriptions-view').classList.toggle('active', viewName === 'subscriptions');
        }

        async function loadSubscriptions() {
            const container = document.getElementById('subscriptions-list');
            const countEl = document.getElementById('subscriptions-count');
            try {
                const response = await fetch('/api/rss-subscriptions');
                const data = await response.json();
                subscriptions = data.subscriptions || [];
                countEl.textContent = `${subscriptions.length} subscriptions`;
                renderSubscriptions();
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><p>Failed to load subscriptions</p></div>';
                countEl.textContent = 'Error loading subscriptions';
            }
        }

        function onSubscriptionsSortChange() {
            const sortEl = document.getElementById('subscriptions-sort');
            subscriptionsSort = sortEl ? sortEl.value : 'domain_asc';
            renderSubscriptions();
        }

        function renderSubscriptions() {
            const container = document.getElementById('subscriptions-list');
            if (!subscriptions.length) {
                container.innerHTML = '<div class="empty-state"><p>No active subscriptions found.</p></div>';
                return;
            }

            const sortedSubscriptions = [...subscriptions];
            if (subscriptionsSort === 'articles_desc') {
                sortedSubscriptions.sort((a, b) => (b.article_count || 0) - (a.article_count || 0));
            } else if (subscriptionsSort === 'articles_asc') {
                sortedSubscriptions.sort((a, b) => (a.article_count || 0) - (b.article_count || 0));
            } else {
                sortedSubscriptions.sort((a, b) => (a.domain || '').localeCompare(b.domain || ''));
            }

            container.innerHTML = sortedSubscriptions.map((sub, index) => {
                const inputId = `subscription-feed-${index}`;
                const updatedAt = sub.updated_at || sub.discovered_at;
                const encodedDomain = encodeURIComponent(sub.domain || '');
                return `
                    <div class="subscription-item">
                        <div class="subscription-top">
                            <div class="subscription-domain">${escapeHtml(sub.domain)}</div>
                            <div class="subscription-meta">${sub.article_count || 0} articles in feed</div>
                        </div>
                        <div class="subscription-meta" style="margin-bottom: 8px;">
                            ${updatedAt ? `Updated: ${new Date(updatedAt).toLocaleString()}` : 'No update timestamp'}
                        </div>
                        <div class="subscription-edit">
                            <input id="${inputId}" type="url" value="${escapeHtml(sub.feed_url || '')}" placeholder="https://example.com/feed.xml" />
                            <div class="subscription-actions">
                                <button class="btn btn-success" onclick="saveSubscriptionByEncoded('${encodedDomain}', '${inputId}')">Save</button>
                                <button class="btn btn-danger" onclick="removeSubscriptionByEncoded('${encodedDomain}', false)">Remove Subscription</button>
                                <button class="btn btn-warning" onclick="removeSubscriptionByEncoded('${encodedDomain}', true)">Remove + Delete Articles</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function decodeDomain(encodedDomain) {
            try {
                return decodeURIComponent(encodedDomain || '');
            } catch (_error) {
                return '';
            }
        }

        function saveSubscriptionByEncoded(encodedDomain, inputId) {
            const domain = decodeDomain(encodedDomain);
            if (!domain) {
                showToast('Invalid subscription domain', 'error');
                return;
            }
            saveSubscription(domain, inputId);
        }

        async function saveSubscription(domain, inputId) {
            const feedUrl = document.getElementById(inputId).value.trim();
            if (!feedUrl) {
                showToast('Feed URL cannot be empty', 'error');
                return;
            }

            try {
                const response = await fetch(`/api/rss-subscriptions/${encodeURIComponent(domain)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ feed_url: feedUrl })
                });

                const result = await response.json();
                if (!response.ok) {
                    showToast(result.error || 'Failed to update subscription', 'error');
                    return;
                }

                showToast(`Subscription updated: ${domain}`, 'success');
                await loadSubscriptions();
            } catch (error) {
                showToast('Failed to update subscription', 'error');
            }
        }

        function removeSubscriptionByEncoded(encodedDomain, deleteArticles) {
            const domain = decodeDomain(encodedDomain);
            if (!domain) {
                showToast('Invalid subscription domain', 'error');
                return;
            }
            removeSubscription(domain, deleteArticles);
        }

        async function removeSubscription(domain, deleteArticles) {
            const prompt = deleteArticles
                ? `Remove ${domain} and delete all related articles from the feed?`
                : `Remove ${domain} subscription?`;
            if (!confirm(prompt)) {
                return;
            }

            try {
                const url = `/api/rss-subscriptions/${encodeURIComponent(domain)}?delete_articles=${deleteArticles ? 'true' : 'false'}`;
                const response = await fetch(url, { method: 'DELETE' });
                const result = await response.json();

                if (!response.ok) {
                    showToast(result.error || 'Failed to remove subscription', 'error');
                    return;
                }

                if (deleteArticles) {
                    showToast(`Removed ${domain} and deleted ${result.deleted_articles || 0} articles`, 'success');
                    await loadArticles();
                } else {
                    showToast(`Removed ${domain} subscription`, 'success');
                }

                await loadSubscriptions();
            } catch (error) {
                showToast('Failed to remove subscription', 'error');
            }
        }

        async function archiveStatus(status) {
            if (!['pending', 'shortlisted', 'rejected'].includes(status)) {
                showToast('Invalid status', 'error');
                return;
            }
            const label = status.charAt(0).toUpperCase() + status.slice(1);
            if (!confirm(`Archive all ${label.toLowerCase()} articles?`)) {
                return;
            }

            const queueList = document.getElementById('queue-list');
            if (queueList) {
                queueScrollTopByStatus[activeQueueStatus] = queueList.scrollTop;
            }

            try {
                const response = await fetch('/api/archive-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status })
                });
                const result = await response.json();
                if (!response.ok) {
                    showToast(result.error || 'Failed to archive', 'error');
                    return;
                }
                showToast(`Archived ${result.archived_count} ${status} article(s)`, 'success');
                await loadArticles();
            } catch (_error) {
                showToast('Failed to archive', 'error');
            }
        }

        async function archiveCurrentFolder() {
            await archiveStatus(activeQueueStatus);
        }

        async function pullFromFeeds() {
            const button = document.getElementById('pull-feeds-btn');
            const original = button ? button.textContent : '';
            if (button) {
                button.disabled = true;
                button.textContent = 'Pulling...';
            }

            try {
                const response = await fetch('/api/sync-feeds', { method: 'POST' });
                const result = await response.json();
                if (!response.ok) {
                    showToast(result.error || 'Failed to pull feeds', 'error');
                    return;
                }
                showToast(`Pulled feeds: ${result.stored_count || 0} article(s) stored`, 'success');
                await loadArticles();
                await loadSubscriptions();
            } catch (_error) {
                showToast('Failed to pull feeds', 'error');
            } finally {
                if (button) {
                    button.disabled = false;
                    button.textContent = original || 'Pull From Feeds';
                }
            }
        }

        async function openArchives() {
            document.getElementById('archives-modal').classList.add('active');
            await loadArchiveWeeks();
            await loadArchivedArticles();
        }

        function closeArchives() {
            document.getElementById('archives-modal').classList.remove('active');
        }

        async function loadArchiveWeeks() {
            try {
                const response = await fetch('/api/archived/weeks');
                const data = await response.json();
                const select = document.getElementById('archive-week-filter');
                select.innerHTML = '<option value="">All weeks</option>' +
                    data.weeks.map(w =>
                        `<option value="${w.week}">${w.week} (${w.shortlisted} shortlisted, ${w.rejected} rejected)</option>`
                    ).join('');
            } catch (error) {
                console.error('Failed to load archive weeks:', error);
            }
        }

        async function loadArchivedArticles() {
            const week = document.getElementById('archive-week-filter').value;
            const container = document.getElementById('archived-list');
            const countEl = document.getElementById('archive-count');

            try {
                const url = week ? `/api/archived?week=${week}` : '/api/archived';
                const response = await fetch(url);
                const data = await response.json();

                countEl.textContent = `${data.count} archived articles`;

                if (data.articles.length === 0) {
                    container.innerHTML = '<div class="empty-state"><p>No archived articles</p></div>';
                    return;
                }

                container.innerHTML = data.articles.map(article => `
                    <div class="archived-item">
                        <div class="archived-item-info">
                            <div class="archived-item-title">
                                <a href="${escapeHtml(article.url)}" target="_blank">${escapeHtml(article.title)}</a>
                            </div>
                            <div class="archived-item-meta">
                                <span class="status-badge status-${article.status}">${article.status}</span>
                                <span>${article.source}</span>
                                <span>Week: ${article.week}</span>
                                <span>Archived: ${new Date(article.archived_at).toLocaleDateString()}</span>
                            </div>
                        </div>
                        <div class="archived-item-actions">
                            <button class="btn btn-primary" onclick="unarchiveArticle('${article.id}')" style="padding: 4px 10px; font-size: 0.75rem;">Unarchive</button>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><p>Failed to load archives</p></div>';
            }
        }

        async function unarchiveArticle(articleId) {
            try {
                const response = await fetch(`/api/articles/${articleId}/unarchive`, { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    showToast('Article unarchived', 'success');
                    await loadArchivedArticles();
                    await loadArticles();
                } else {
                    showToast('Failed to unarchive', 'error');
                }
            } catch (error) {
                showToast('Failed to unarchive', 'error');
            }
        }

        function setQueueStatus(status) {
            if (!queueStatuses.includes(status)) return;
            const queueList = document.getElementById('queue-list');
            if (queueList) {
                queueScrollTopByStatus[activeQueueStatus] = queueList.scrollTop;
            }
            activeQueueStatus = status;
            renderQueue({ preserveScroll: true, animate: false });
            syncReaderSelection();
        }

        function getQueueItems() {
            return articles[activeQueueStatus] || [];
        }

        function renderQueue(options = {}) {
            const preserveScroll = options.preserveScroll !== false;
            const animate = options.animate !== false;
            queueStatuses.forEach(status => {
                const countEl = document.getElementById(`count-${status}`);
                const filterEl = document.getElementById(`queue-filter-${status}`);
                const count = (articles[status] || []).length;
                if (countEl) countEl.textContent = count;
                if (filterEl) filterEl.classList.toggle('active', activeQueueStatus === status);
            });

            const container = document.getElementById('queue-list');
            const previousScrollTop = container ? container.scrollTop : 0;
            const items = getQueueItems();
            if (!items.length) {
                container.innerHTML = `<div class="empty-state"><p>No ${activeQueueStatus} articles</p></div>`;
                queueScrollTopByStatus[activeQueueStatus] = 0;
                return;
            }

            container.innerHTML = items.map((article, idx) => {
                const isActive = article.id === activeReaderArticleId;
                const summary = article.summary
                    ? (article.summary.length > 120 ? article.summary.substring(0, 120) + '...' : article.summary)
                    : '';
                const animationStyle = animate
                    ? `animation-delay: ${Math.min(idx * 28, 280)}ms;`
                    : 'animation: none; opacity: 1; transform: translateY(0);';
                return `
                    <article class="queue-item ${isActive ? 'active' : ''}" data-article-id="${article.id}" tabindex="0" style="${animationStyle}" onclick="openReader('${article.id}')">
                        <div class="queue-item-top">
                            <h3 class="queue-item-title">${escapeHtml(article.title)}</h3>
                            ${article.top_pick ? '<span class="queue-pill top-pick">Top Pick</span>' : ''}
                        </div>
                        <div class="queue-item-meta">
                            <span class="queue-pill source">${escapeHtml(article.source)}</span>
                            ${article.topic ? `<span class="queue-pill topic">${escapeHtml(article.topic)}</span>` : ''}
                        </div>
                        ${summary ? `<p class="queue-item-summary">${escapeHtml(summary)}</p>` : ''}
                        <div class="queue-item-actions">
                            ${renderQueueActions(article.id, activeQueueStatus)}
                        </div>
                    </article>
                `;
            }).join('');

            if (container) {
                const savedScrollTop = queueScrollTopByStatus[activeQueueStatus] || previousScrollTop || 0;
                container.scrollTop = preserveScroll ? savedScrollTop : 0;
            }
        }

        function renderQueueActions(articleId, currentStatus) {
            if (currentStatus === 'pending') {
                return `
                    <button class="btn btn-success" onclick="event.stopPropagation(); curate('${articleId}', 'shortlisted')">Shortlist</button>
                    <button class="btn btn-danger" onclick="event.stopPropagation(); curate('${articleId}', 'rejected')">Reject</button>
                    <button class="btn btn-feed-remove" onclick="event.stopPropagation(); removeFeedForArticle('${articleId}', true)">Remove Feed</button>
                `;
            }
            if (currentStatus === 'shortlisted') {
                return `
                    <button class="btn btn-secondary" onclick="event.stopPropagation(); curate('${articleId}', 'pending')">Reset</button>
                    <button class="btn btn-danger" onclick="event.stopPropagation(); curate('${articleId}', 'rejected')">Reject</button>
                    <button class="btn btn-feed-remove" onclick="event.stopPropagation(); removeFeedForArticle('${articleId}', true)">Remove Feed</button>
                `;
            }
            return `
                <button class="btn btn-secondary" onclick="event.stopPropagation(); curate('${articleId}', 'pending')">Reset</button>
                <button class="btn btn-success" onclick="event.stopPropagation(); curate('${articleId}', 'shortlisted')">Shortlist</button>
                <button class="btn btn-feed-remove" onclick="event.stopPropagation(); removeFeedForArticle('${articleId}', true)">Remove Feed</button>
            `;
        }

        function syncReaderSelection() {
            const items = getQueueItems();
            if (!items.length) {
                closeReader();
                return;
            }
            const stillExists = items.some(a => a.id === activeReaderArticleId);
            if (!stillExists) {
                const fallbackIndex = typeof nextQueueIndexAfterMutation === 'number'
                    ? Math.min(nextQueueIndexAfterMutation, items.length - 1)
                    : 0;
                nextQueueIndexAfterMutation = null;
                openReader(items[fallbackIndex].id, { refreshQueue: false, animatedSwitch: true });
                return;
            }
            nextQueueIndexAfterMutation = null;
            openReader(activeReaderArticleId, { refreshQueue: false, animatedSwitch: false });
        }

        async function curate(articleId, status) {
            try {
                const currentQueueItems = getQueueItems();
                const currentIndex = currentQueueItems.findIndex(item => item.id === articleId);
                if (currentIndex >= 0) {
                    nextQueueIndexAfterMutation = currentIndex;
                }
                const queueList = document.getElementById('queue-list');
                if (queueList) {
                    queueScrollTopByStatus[activeQueueStatus] = queueList.scrollTop;
                }
                await animateStatusTransition(articleId, status);

                const response = await fetch(`/api/articles/${articleId}/curate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status })
                });

                if (response.ok) {
                    await loadArticles();
                    showToast(`Article ${status}`, 'success');
                } else {
                    showToast('Failed to update article', 'error');
                }
            } catch (error) {
                showToast('Failed to update article', 'error');
            }
        }

        async function toggleTopPick(articleId, topPick) {
            try {
                const response = await fetch(`/api/articles/${articleId}/top-pick`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ top_pick: topPick })
                });

                if (response.ok) {
                    await loadArticles();
                    showToast(topPick ? 'Marked as Top Pick' : 'Top Pick removed', 'success');
                } else {
                    showToast('Failed to update Top Pick', 'error');
                }
            } catch (error) {
                showToast('Failed to update Top Pick', 'error');
            }
        }

        function normalizeHost(value) {
            return (value || '').toLowerCase().replace(/^www\./, '');
        }

        function extractHost(url) {
            if (!url) return '';
            try {
                return normalizeHost(new URL(url).hostname);
            } catch (_error) {
                return '';
            }
        }

        function resolveSubscriptionDomainForArticle(article) {
            const sourceHost = normalizeHost(article?.source || '');
            const articleHost = extractHost(article?.url || '');
            const candidates = [sourceHost, articleHost].filter(Boolean);
            if (!candidates.length) return '';

            const match = subscriptions.find(sub => {
                const subDomainHost = normalizeHost(sub.domain || '');
                const subFeedHost = extractHost(sub.feed_url || '');
                return candidates.some(candidate =>
                    candidate === subDomainHost || candidate === subFeedHost
                );
            });
            return match ? match.domain : '';
        }

        async function removeFeedForArticle(articleId, deleteArticles = true) {
            const article = findArticleById(articleId);
            if (!article) {
                showToast('Article not found', 'error');
                return;
            }

            if (!subscriptions.length) {
                await loadSubscriptions();
            }
            const domain = resolveSubscriptionDomainForArticle(article);
            if (!domain) {
                showToast('Could not map article to an RSS subscription', 'error');
                return;
            }

            const prompt = deleteArticles
                ? `Remove feed "${domain}" and delete all related articles?`
                : `Remove feed "${domain}" subscription?`;
            if (!confirm(prompt)) {
                return;
            }

            const currentQueueItems = getQueueItems();
            const currentIndex = currentQueueItems.findIndex(item => item.id === articleId);
            if (currentIndex >= 0) {
                nextQueueIndexAfterMutation = currentIndex;
            }
            const queueList = document.getElementById('queue-list');
            if (queueList) {
                queueScrollTopByStatus[activeQueueStatus] = queueList.scrollTop;
            }

            try {
                const url = `/api/rss-subscriptions/${encodeURIComponent(domain)}?delete_articles=${deleteArticles ? 'true' : 'false'}`;
                const response = await fetch(url, { method: 'DELETE' });
                const result = await response.json();
                if (!response.ok) {
                    showToast(result.error || 'Failed to remove feed subscription', 'error');
                    return;
                }

                showToast(
                    deleteArticles
                        ? `Removed ${domain} and deleted ${result.deleted_articles || 0} related articles`
                        : `Removed ${domain} subscription`,
                    'success'
                );
                await loadSubscriptions();
                await loadArticles();
            } catch (_error) {
                showToast('Failed to remove feed subscription', 'error');
            }
        }

        function saveNotes(articleId, notes) {
            setNotesSaveState('saving', 'Saving notes...');
            // Debounce saves
            if (notesSaveTimeout[articleId]) {
                clearTimeout(notesSaveTimeout[articleId]);
            }
            if (notesStatusResetTimeout) {
                clearTimeout(notesStatusResetTimeout);
            }

            notesSaveTimeout[articleId] = setTimeout(async () => {
                try {
                    const response = await fetch(`/api/articles/${articleId}/curate`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ notes })
                    });
                    if (!response.ok) throw new Error('Failed to save notes');
                    setNotesSaveState('saved', 'Saved');
                    notesStatusResetTimeout = setTimeout(() => {
                        setNotesSaveState('idle', 'Notes auto-save as you type.');
                    }, 1400);
                } catch (error) {
                    console.error('Failed to save notes:', error);
                    setNotesSaveState('error', 'Save failed. Retrying on next edit.');
                }
            }, 500);
        }

        async function generateNewsletter() {
            const shortlistedCount = articles.shortlisted.length;
            if (shortlistedCount === 0) {
                showToast('No shortlisted articles to include', 'error');
                return;
            }

            showToast('Generating newsletter...', 'success');

            try {
                const response = await fetch('/api/generate-newsletter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });

                const result = await response.json();

                if (result.success) {
                    showToast(`Newsletter generated with ${result.article_count} articles`, 'success');
                    viewNewsletter(result.newsletter_id);
                } else {
                    showToast(result.error || 'Failed to generate newsletter', 'error');
                }
            } catch (error) {
                showToast('Failed to generate newsletter', 'error');
            }
        }

        async function viewNewsletter(selectedWeek = null) {
            const modal = document.getElementById('newsletter-modal');
            const listContainer = document.getElementById('newsletter-list');
            const content = document.getElementById('newsletter-content');

            modal.classList.add('active');
            listContainer.innerHTML = '<h3>Past Newsletters</h3><div class="loading">Loading...</div>';

            try {
                // Load list of newsletters
                const listResponse = await fetch('/api/newsletters');
                const listData = await listResponse.json();

                if (listData.newsletters.length === 0) {
                    listContainer.innerHTML = '<h3>Past Newsletters</h3><div class="empty-state"><p>No newsletters generated yet.</p></div>';
                    content.innerHTML = '<div class="empty-state"><p>Shortlist some articles and click "Generate Newsletter".</p></div>';
                    return;
                }

                listContainer.innerHTML = '<h3>Past Newsletters</h3>' +
                    listData.newsletters.map(n => `
                        <div class="newsletter-item" data-id="${n.id}"
                             onclick="loadNewsletterContent('${n.id}')">
                            <span>${n.week}</span>
                            <span style="font-size: 0.8rem; opacity: 0.7;">${new Date(n.generated_at).toLocaleString()}</span>
                        </div>
                    `).join('');

                // Load selected or most recent newsletter
                const idToLoad = selectedWeek || listData.newsletters[0].id;
                await loadNewsletterContent(idToLoad);

            } catch (error) {
                listContainer.innerHTML = '<h3>Past Newsletters</h3><div class="empty-state"><p>Failed to load newsletters.</p></div>';
            }
        }

        async function loadNewsletterContent(newsletterId) {
            const content = document.getElementById('newsletter-content');
            content.innerHTML = '<div class="loading">Loading...</div>';

            // Update active state in list
            document.querySelectorAll('.newsletter-item').forEach(item => {
                item.classList.toggle('active', item.dataset.id === newsletterId);
            });

            try {
                const response = await fetch(`/api/newsletter/${newsletterId}`);
                if (response.ok) {
                    const data = await response.json();
                    content.innerHTML = markdownToHtml(data.content);
                } else {
                    content.innerHTML = '<div class="empty-state"><p>Newsletter not found.</p></div>';
                }
            } catch (error) {
                content.innerHTML = '<div class="empty-state"><p>Failed to load newsletter.</p></div>';
            }
        }

        function closeModal() {
            document.getElementById('newsletter-modal').classList.remove('active');
        }

        function openAddArticle() {
            document.getElementById('add-article-modal').classList.add('active');
            document.getElementById('article-url').focus();
        }

        function findArticleById(articleId) {
            const all = [...articles.pending, ...articles.shortlisted, ...articles.rejected];
            return all.find(article => article.id === articleId);
        }

        function openReader(articleId, options = {}) {
            const article = findArticleById(articleId);
            if (!article) {
                showToast('Article not found', 'error');
                return;
            }

            const refreshQueue = options.refreshQueue !== false;
            const animatedSwitch = options.animatedSwitch !== false;
            activeReaderArticleId = articleId;
            if (refreshQueue) {
                renderQueue({ preserveScroll: true, animate: false });
            }
            if (animatedSwitch) {
                const readerPanel = document.querySelector('.reader-panel');
                if (readerPanel) {
                    readerPanel.classList.remove('reader-switching');
                    void readerPanel.offsetWidth;
                    readerPanel.classList.add('reader-switching');
                    setTimeout(() => readerPanel.classList.remove('reader-switching'), 220);
                }
            }

            const titleEl = document.getElementById('reader-title');
            const metaEl = document.getElementById('reader-meta');
            const openLink = document.getElementById('reader-open-link');
            const iframe = document.getElementById('reader-iframe');
            const notesInput = document.getElementById('reader-notes-input');
            const resetBtn = document.getElementById('reader-reset');
            const removeFeedBtn = document.getElementById('reader-remove-feed');
            const topPickBtn = document.getElementById('reader-top-pick');
            const currentStatus = article.status || 'pending';

            titleEl.textContent = article.title || 'Article';
            metaEl.innerHTML = `
                <span>${escapeHtml(article.source || '')}</span>
                ${article.topic ? `<span>Topic: ${escapeHtml(article.topic)}</span>` : ''}
                <span>Status: ${escapeHtml(currentStatus)}</span>
            `;

            openLink.href = article.url;
            iframe.src = article.url;
            notesInput.value = article.user_notes || '';
            notesInput.oninput = () => saveNotes(articleId, notesInput.value);
            setNotesSaveState('idle', 'Notes auto-save as you type.');

            const shortlistBtn = document.getElementById('reader-shortlist');
            const rejectBtn = document.getElementById('reader-reject');
            shortlistBtn.style.display = currentStatus === 'shortlisted' ? 'none' : 'inline-flex';
            rejectBtn.style.display = currentStatus === 'rejected' ? 'none' : 'inline-flex';
            resetBtn.style.display = currentStatus === 'pending' ? 'none' : 'inline-flex';
            topPickBtn.style.display = currentStatus === 'shortlisted' ? 'inline-flex' : 'none';
            topPickBtn.classList.toggle('active', !!article.top_pick);

            shortlistBtn.onclick = async () => {
                await curate(articleId, 'shortlisted');
            };
            rejectBtn.onclick = async () => {
                await curate(articleId, 'rejected');
            };
            resetBtn.onclick = async () => {
                await curate(articleId, 'pending');
            };
            removeFeedBtn.onclick = async () => {
                await removeFeedForArticle(articleId, true);
            };
            topPickBtn.onclick = async () => {
                await toggleTopPick(articleId, !article.top_pick);
            };
        }

        function closeReader() {
            document.getElementById('reader-title').textContent = 'Select an article';
            document.getElementById('reader-meta').innerHTML = '';
            document.getElementById('reader-iframe').src = 'about:blank';
            document.getElementById('reader-notes-input').value = '';
            document.getElementById('reader-open-link').removeAttribute('href');
            setNotesSaveState('idle', 'Notes auto-save as you type.');
            activeReaderArticleId = null;
            renderQueue({ preserveScroll: true, animate: false });
        }

        function closeAddArticle() {
            document.getElementById('add-article-modal').classList.remove('active');
            document.getElementById('add-article-form').reset();
        }

        async function fetchMetadata() {
            const url = document.getElementById('article-url').value.trim();
            if (!url) {
                showToast('Please enter a URL first', 'error');
                return;
            }

            showToast('Fetching article metadata...', 'success');

            try {
                const response = await fetch('/api/fetch-url', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });

                const data = await response.json();

                if (data.success) {
                    if (data.title) {
                        document.getElementById('article-title').value = data.title;
                    }
                    if (data.summary) {
                        document.getElementById('article-summary').value = data.summary;
                    }
                    showToast('Metadata fetched!', 'success');
                } else {
                    showToast('Could not fetch metadata: ' + (data.error || 'Unknown error'), 'error');
                }
            } catch (error) {
                showToast('Failed to fetch metadata', 'error');
            }
        }

        async function submitArticle(event) {
            event.preventDefault();

            const url = document.getElementById('article-url').value.trim();
            const title = document.getElementById('article-title').value.trim();

            if (!url || !title) {
                showToast('URL and title are required', 'error');
                return;
            }

            try {
                const response = await fetch('/api/articles/manual', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: url,
                        title: title,
                        summary: document.getElementById('article-summary').value.trim(),
                        topic: document.getElementById('article-topic').value,
                        notes: document.getElementById('article-notes').value.trim(),
                        auto_shortlist: document.getElementById('article-shortlist').checked
                    })
                });

                const result = await response.json();

                if (result.success) {
                    showToast('Article added successfully!', 'success');
                    closeAddArticle();
                    await loadArticles();
                } else {
                    showToast(result.error || 'Failed to add article', 'error');
                }
            } catch (error) {
                showToast('Failed to add article', 'error');
            }
        }

        async function migrateData() {
            try {
                const response = await fetch('/api/migrate', { method: 'POST' });
                const result = await response.json();

                if (result.success) {
                    showToast(`Migrated ${result.migrated} articles`, 'success');
                    await loadArticles();
                } else {
                    showToast('Migration failed', 'error');
                }
            } catch (error) {
                showToast('Migration failed', 'error');
            }
        }

        function handleQueueKeyboardShortcuts(event) {
            if (activeView !== 'articles') return;
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const target = event.target;
            if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;

            const items = getQueueItems();
            if (!items.length) return;
            const currentIndex = items.findIndex(item => item.id === activeReaderArticleId);
            const safeIndex = currentIndex >= 0 ? currentIndex : 0;

            if (event.key === 'j' || event.key === 'J') {
                event.preventDefault();
                const nextIndex = Math.min(items.length - 1, safeIndex + 1);
                openReader(items[nextIndex].id);
                return;
            }
            if (event.key === 'k' || event.key === 'K') {
                event.preventDefault();
                const prevIndex = Math.max(0, safeIndex - 1);
                openReader(items[prevIndex].id);
                return;
            }
            if (!activeReaderArticleId) return;
            if (event.key === 's' || event.key === 'S') {
                event.preventDefault();
                curate(activeReaderArticleId, 'shortlisted');
                return;
            }
            if (event.key === 'r' || event.key === 'R') {
                event.preventDefault();
                curate(activeReaderArticleId, 'rejected');
                return;
            }
            if (event.key === 'n' || event.key === 'N') {
                event.preventDefault();
                document.getElementById('reader-notes-input').focus();
            }
        }

        function setNotesSaveState(state, message) {
            const statusEl = document.getElementById('notes-save-status');
            if (!statusEl) return;
            statusEl.className = `notes-save-status ${state}`;
            statusEl.textContent = message;
        }

        async function animateStatusTransition(articleId, status) {
            const item = document.querySelector(`.queue-item[data-article-id="${articleId}"]`);
            if (!item) return;
            item.classList.remove('status-shift-shortlisted', 'status-shift-rejected', 'status-shift-pending');
            item.classList.add(`status-shift-${status}`);
            await new Promise(resolve => setTimeout(resolve, 170));
        }

        function markdownToHtml(markdown) {
            if (!markdown) return '';

            return markdown
                .replace(/^### \[(.*?)\]\((.*?)\)/gm, '<h3><a href="$2" target="_blank">$1</a></h3>')
                .replace(/^## (.*$)/gm, '<h2>$1</h2>')
                .replace(/^# (.*$)/gm, '<h1>$1</h1>')
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                .replace(/^> (.*$)/gm, '<blockquote>$1</blockquote>')
                .replace(/^- (.*$)/gm, '<li>$1</li>')
                .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
                .replace(/^---$/gm, '<hr>')
                .replace(/\n\n/g, '</p><p>')
                .replace(/\n/g, '<br>');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        }

        function showToast(message, type = 'success') {
            const existing = document.querySelector('.toast');
            if (existing) existing.remove();

            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            document.body.appendChild(toast);

            setTimeout(() => toast.remove(), 3000);
        }

        // Event listeners
        const newsletterModal = document.getElementById('newsletter-modal');
        if (newsletterModal) {
            newsletterModal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal')) closeModal();
            });
        }
        const addModal = document.getElementById('add-article-modal');
        if (addModal) {
            addModal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal')) closeAddArticle();
            });
        }
        const archivesModal = document.getElementById('archives-modal');
        if (archivesModal) {
            archivesModal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal')) closeArchives();
            });
        }
        document.addEventListener('keydown', handleQueueKeyboardShortcuts);
        const queueList = document.getElementById('queue-list');
        if (queueList) {
            queueList.addEventListener('scroll', () => {
                queueScrollTopByStatus[activeQueueStatus] = queueList.scrollTop;
            });
        }

        window.archiveCurrentFolder = archiveCurrentFolder;
        window.archiveStatus = archiveStatus;
        window.closeAddArticle = closeAddArticle;
        window.closeArchives = closeArchives;
        window.closeModal = closeModal;
        window.closeReader = closeReader;
        window.curate = curate;
        window.fetchMetadata = fetchMetadata;
        window.generateNewsletter = generateNewsletter;
        window.loadNewsletterContent = loadNewsletterContent;
        window.openAddArticle = openAddArticle;
        window.openArchives = openArchives;
        window.onSubscriptionsSortChange = onSubscriptionsSortChange;
        window.openReader = openReader;
        window.pullFromFeeds = pullFromFeeds;
        window.removeFeedForArticle = removeFeedForArticle;
        window.removeSubscriptionByEncoded = removeSubscriptionByEncoded;
        window.saveSubscriptionByEncoded = saveSubscriptionByEncoded;
        window.setQueueStatus = setQueueStatus;
        window.submitArticle = submitArticle;
        window.switchView = switchView;
        window.toggleTopPick = toggleTopPick;
        window.unarchiveArticle = unarchiveArticle;
        window.viewNewsletter = viewNewsletter;

        // Initialize
        init();

export {};
