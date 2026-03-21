// SNS Metadata Extractor - Frontend JavaScript

class MetadataExtractor {
    constructor() {
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        // Form elements
        this.urlForm = document.getElementById('urlForm');
        this.urlInput = document.getElementById('urlInput');
        this.extractBtn = document.getElementById('extractBtn');

        // Section elements
        this.loadingSection = document.getElementById('loadingSection');
        this.resultsSection = document.getElementById('resultsSection');
        this.errorSection = document.getElementById('errorSection');
        this.playlistSection = document.getElementById('playlistSection');

        // Result display elements
        this.platformBadge = document.getElementById('platformBadge');
        this.titleDisplay = document.getElementById('titleDisplay');
        this.authorDisplay = document.getElementById('authorDisplay');
        this.videoIdDisplay = document.getElementById('videoIdDisplay');
        this.thumbnailContainer = document.getElementById('thumbnailContainer');
        this.thumbnailPlaceholder = document.getElementById('thumbnailPlaceholder');
        this.thumbnailImage = document.getElementById('thumbnailImage');
        this.thumbnailUrl = document.getElementById('thumbnailUrl');
        this.thumbnailLink = document.getElementById('thumbnailLink');
        this.jsonResponse = document.getElementById('jsonResponse');
        this.errorMessage = document.getElementById('errorMessage');
        this.playlistVideos = document.getElementById('playlistVideos');

        // Control elements
        this.clearResults = document.getElementById('clearResults');
        this.exampleUrlButtons = document.querySelectorAll('.example-url');
        
        // Ranking test elements
        this.rankingTestBtn = document.getElementById('rankingTestBtn');
        this.rankingProgressSection = document.getElementById('rankingProgressSection');
        this.rankingResultSection = document.getElementById('rankingResultSection');
        this.rankingAlert = document.getElementById('rankingAlert');
        this.rankingIcon = document.getElementById('rankingIcon');
        this.rankingStatus = document.getElementById('rankingStatus');
        this.rankingMessage = document.getElementById('rankingMessage');
        this.rankingTime = document.getElementById('rankingTime');
    }

    bindEvents() {
        // Form submission
        this.urlForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.extractMetadata();
        });

        // Clear results
        this.clearResults.addEventListener('click', () => {
            this.clearAllResults();
        });

        // Example URL buttons
        this.exampleUrlButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const url = e.target.closest('.example-url').dataset.url;
                this.urlInput.value = url;
                this.urlInput.focus();
            });
        });

        // Auto-clear results when URL changes
        this.urlInput.addEventListener('input', () => {
            if (this.resultsSection.style.display !== 'none' || 
                this.errorSection.style.display !== 'none') {
                this.clearAllResults();
            }
        });

        // Ranking test button
        if (this.rankingTestBtn) {
            this.rankingTestBtn.addEventListener('click', () => {
                this.runRankingTest();
            });
        }
    }

    async extractMetadata() {
        const url = this.urlInput.value.trim();
        
        if (!url) {
            this.showError('有効なURLを入力してください');
            return;
        }

        try {
            this.showLoading();
            
            const response = await fetch('/api/v2/get-metadata', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            const metadata = await response.json();
            this.displayResults(metadata);

        } catch (error) {
            console.error('Error extracting metadata:', error);
            this.showError(`メタデータの抽出に失敗しました: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    showLoading() {
        this.loadingSection.style.display = 'block';
        this.resultsSection.style.display = 'none';
        this.errorSection.style.display = 'none';
        this.playlistSection.style.display = 'none';
        this.extractBtn.disabled = true;
        this.extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>処理中...';
    }

    hideLoading() {
        this.loadingSection.style.display = 'none';
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-magic me-2"></i>メタデータを抽出';
    }

    displayResults(metadata) {
        // Show results section
        this.resultsSection.style.display = 'block';
        this.errorSection.style.display = 'none';

        // Update platform badge
        this.updatePlatformBadge(metadata.platform);

        // Update metadata displays
        this.titleDisplay.textContent = metadata.title || '取得できませんでした';
        this.authorDisplay.textContent = metadata.authorName || '取得できませんでした';
        this.videoIdDisplay.textContent = metadata.unique_video_id || '取得できませんでした';

        // Update thumbnail
        this.updateThumbnail(metadata.thumbnailUrl);

        // Update playlist if available
        this.updatePlaylist(metadata);

        // Update JSON response
        this.jsonResponse.textContent = JSON.stringify(metadata, null, 2);

        // Scroll to results
        this.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    updatePlatformBadge(platform) {
        const platformInfo = {
            youtube: { 
                icon: 'fab fa-youtube', 
                text: 'YouTube',
                class: 'bg-danger'
            },
            tiktok: { 
                icon: 'fab fa-tiktok', 
                text: 'TikTok',
                class: 'bg-dark'
            },
            instagram: { 
                icon: 'fab fa-instagram', 
                text: 'Instagram',
                class: 'bg-warning'
            },
            youtube_playlist: { 
                icon: 'fab fa-youtube', 
                text: 'YouTubeプレイリスト',
                class: 'bg-danger'
            },
            other: { 
                icon: 'fas fa-question', 
                text: '不明',
                class: 'bg-secondary'
            }
        };

        const info = platformInfo[platform] || platformInfo.other;
        
        this.platformBadge.className = `badge fs-6 ${info.class}`;
        this.platformBadge.innerHTML = `<i class="${info.icon} me-1"></i>${info.text}`;
    }

    updateThumbnail(thumbnailUrl) {
        if (thumbnailUrl) {
            // Hide placeholder, show image and URL
            this.thumbnailPlaceholder.style.display = 'none';
            this.thumbnailImage.style.display = 'block';
            this.thumbnailUrl.style.display = 'block';

            // Set image source
            this.thumbnailImage.src = thumbnailUrl;
            this.thumbnailImage.onerror = () => {
                // If image fails to load, show placeholder
                this.showThumbnailPlaceholder();
            };

            // Set thumbnail URL link
            this.thumbnailLink.href = thumbnailUrl;
            this.thumbnailLink.textContent = this.truncateUrl(thumbnailUrl);
        } else {
            this.showThumbnailPlaceholder();
        }
    }

    showThumbnailPlaceholder() {
        this.thumbnailPlaceholder.style.display = 'block';
        this.thumbnailImage.style.display = 'none';
        this.thumbnailUrl.style.display = 'none';
    }

    updatePlaylist(metadata) {
        if (metadata.platform === 'youtube_playlist' && metadata.playlist_videos) {
            this.playlistSection.style.display = 'block';
            
            // Create playlist HTML
            let playlistHtml = `
                <div class="mb-3">
                    <strong class="text-info">
                        <i class="fas fa-video me-2"></i>
                        ${metadata.video_count}個の動画が見つかりました
                    </strong>
                </div>
                <div class="row g-3">
            `;
            
            metadata.playlist_videos.forEach((video, index) => {
                playlistHtml += `
                    <div class="col-md-6 col-lg-4">
                        <div class="card bg-dark border-secondary h-100">
                            <div class="card-body p-3">
                                <div class="d-flex align-items-start">
                                    <span class="badge bg-info me-2 mt-1">${index + 1}</span>
                                    <div class="flex-grow-1">
                                        <h6 class="card-title text-light mb-2" style="font-size: 0.85rem; line-height: 1.3;">
                                            ${this.truncateText(video.title || '無題', 60)}
                                        </h6>
                                        <div class="d-flex gap-2">
                                            <a href="${video.videoUrl}" target="_blank" class="btn btn-outline-info btn-sm">
                                                <i class="fas fa-external-link-alt me-1"></i>
                                                視聴
                                            </a>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            });
            
            playlistHtml += '</div>';
            this.playlistVideos.innerHTML = playlistHtml;
        } else {
            this.playlistSection.style.display = 'none';
        }
    }

    truncateUrl(url, maxLength = 50) {
        if (url.length <= maxLength) return url;
        return url.substring(0, maxLength - 3) + '...';
    }

    truncateText(text, maxLength = 100) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 3) + '...';
    }

    showError(message) {
        this.errorSection.style.display = 'block';
        this.resultsSection.style.display = 'none';
        this.errorMessage.textContent = message;
        
        // Scroll to error
        this.errorSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    clearAllResults() {
        // Hide all result sections
        this.resultsSection.style.display = 'none';
        this.errorSection.style.display = 'none';
        this.loadingSection.style.display = 'none';
        this.playlistSection.style.display = 'none';

        // Reset displays
        this.platformBadge.className = 'badge bg-info fs-6';
        this.platformBadge.innerHTML = '<i class="fas fa-tag me-1"></i>プラットフォーム';
        this.titleDisplay.textContent = '-';
        this.authorDisplay.textContent = '-';
        this.videoIdDisplay.textContent = '-';
        this.jsonResponse.textContent = 'データがありません';
        
        // Reset thumbnail
        this.showThumbnailPlaceholder();
        
        // Reset button
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-magic me-2"></i>メタデータを抽出';
    }

    async runRankingTest() {
        try {
            this.showRankingProgress();
            
            const response = await fetch('/api/rankings/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            const result = await response.json();
            
            if (response.ok && result.success) {
                this.showRankingSuccess(result);
            } else {
                this.showRankingError(result);
            }

        } catch (error) {
            console.error('Ranking test error:', error);
            this.showRankingError({ error: `処理エラー: ${error.message}` });
        } finally {
            this.hideRankingProgress();
        }
    }

    showRankingProgress() {
        this.rankingTestBtn.disabled = true;
        this.rankingTestBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>実行中...';
        this.rankingProgressSection.style.display = 'block';
        this.rankingResultSection.style.display = 'none';
    }

    hideRankingProgress() {
        this.rankingTestBtn.disabled = false;
        this.rankingTestBtn.innerHTML = '<i class="fas fa-play-circle me-2"></i>ランキング処理テスト';
        this.rankingProgressSection.style.display = 'none';
    }

    showRankingSuccess(result) {
        this.rankingResultSection.style.display = 'block';
        this.rankingAlert.className = 'alert alert-success mb-0';
        this.rankingIcon.className = 'fas fa-check-circle me-2';
        this.rankingStatus.textContent = '✅ 正常終了';
        
        let message = `ランキング処理が正常に完了しました。`;
        if (result.stats) {
            message += `\n総ランキング数: ${result.stats.total_rankings || 0}件`;
            if (result.stats.periods) {
                message += '\n期間別: ';
                Object.entries(result.stats.periods).forEach(([period, info]) => {
                    message += `${period}(${info.count}件) `;
                });
            }
        }
        
        this.rankingMessage.textContent = message;
        this.rankingTime.textContent = `実行時刻: ${new Date().toLocaleString('ja-JP')}`;
    }

    showRankingError(result) {
        const errorMsg = result.error || result.message || 'ランキング処理でエラーが発生しました';
        const technicalError = result.technical_error || null;
        const executionTime = result.execution_time != null ? `${result.execution_time}秒` : null;

        this.rankingResultSection.style.display = 'block';
        this.rankingAlert.className = 'alert alert-danger mb-0';
        this.rankingIcon.className = 'fas fa-exclamation-triangle me-2';
        this.rankingStatus.textContent = '❌ 異常終了';
        this.rankingMessage.textContent = `エラー: ${errorMsg}`;

        let timeText = `実行時刻: ${new Date().toLocaleString('ja-JP')}`;
        if (executionTime) timeText += ` （実行時間: ${executionTime}）`;
        this.rankingTime.textContent = timeText;

        const existingDetail = document.getElementById('rankingTechnicalDetail');
        if (existingDetail) existingDetail.remove();

        if (technicalError) {
            const detail = document.createElement('div');
            detail.id = 'rankingTechnicalDetail';
            detail.className = 'mt-2';
            detail.innerHTML = `
                <div class="small text-danger-emphasis fw-semibold mb-1">
                    <i class="fas fa-bug me-1"></i>技術的なエラーログ:
                </div>
                <pre class="bg-dark text-danger-emphasis border border-danger rounded p-2 small mb-0" style="white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto;">${this.escapeHtml(technicalError)}</pre>`;
            this.rankingAlert.appendChild(detail);
        }
    }

    escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}

class CollectionExtractor {
    constructor() {
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        this.apiKeyInput = document.getElementById('collectionApiKey');
        this.fileInput = document.getElementById('collectionFile');
        this.extractBtn = document.getElementById('extractCollectionBtn');
        this.loadingSection = document.getElementById('collectionLoadingSection');
        this.progressText = document.getElementById('collectionProgressText');
        this.progressBar = document.getElementById('collectionProgressBar');
        this.errorSection = document.getElementById('collectionErrorSection');
        this.errorMessage = document.getElementById('collectionErrorMessage');
        this.resultsSection = document.getElementById('collectionResultsSection');
        this.collectionName = document.getElementById('collectionName');
        this.successCount = document.getElementById('successCount');
        this.failCount = document.getElementById('failCount');
        this.sourceFileName = document.getElementById('sourceFileName');
        this.resultsBody = document.getElementById('collectionResultsBody');
        this.jsonResponse = document.getElementById('collectionJsonResponse');
        this.clearBtn = document.getElementById('clearCollectionResults');
    }

    bindEvents() {
        this.extractBtn.addEventListener('click', () => this.extractCollection());
        this.clearBtn.addEventListener('click', () => this.clearResults());
        
        this.fileInput.addEventListener('change', () => {
            if (this.resultsSection.style.display !== 'none' || 
                this.errorSection.style.display !== 'none') {
                this.clearResults();
            }
        });
    }

    async extractCollection() {
        const apiKey = this.apiKeyInput.value.trim();
        const file = this.fileInput.files[0];

        if (!apiKey) {
            this.showError('APIキーを入力してください');
            return;
        }

        if (!file) {
            this.showError('ファイルを選択してください');
            return;
        }

        try {
            this.showLoading();
            this.updateProgress('ファイルをアップロード中...', 10);

            const formData = new FormData();
            formData.append('file', file);

            this.updateProgress('サーバーで処理中...', 30);

            const response = await fetch('/api/extract-collection-metadata', {
                method: 'POST',
                headers: {
                    'X-API-Key': apiKey
                },
                body: formData
            });

            this.updateProgress('レスポンスを処理中...', 70);

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            if (!result.success) {
                throw new Error(result.error || 'コレクションの処理に失敗しました');
            }

            this.updateProgress('完了!', 100);
            this.displayResults(result);

        } catch (error) {
            console.error('Collection extraction error:', error);
            this.showError(error.message);
        } finally {
            this.hideLoading();
        }
    }

    showLoading() {
        this.loadingSection.style.display = 'block';
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'none';
        this.extractBtn.disabled = true;
        this.extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>処理中...';
    }

    hideLoading() {
        this.loadingSection.style.display = 'none';
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-cloud-upload-alt me-2"></i>メタデータを取得';
    }

    updateProgress(text, percent) {
        this.progressText.textContent = text;
        this.progressBar.style.width = `${percent}%`;
    }

    showError(message) {
        this.errorSection.style.display = 'block';
        this.resultsSection.style.display = 'none';
        this.errorMessage.textContent = message;
    }

    displayResults(result) {
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'block';

        this.collectionName.textContent = result.collection_name || '名称なし';
        this.successCount.textContent = `${result.successful}件成功`;
        this.failCount.textContent = `${result.failed}件失敗`;
        this.sourceFileName.textContent = `ソースファイル: ${result.source_file}`;

        this.resultsBody.innerHTML = '';

        result.results.forEach((item, index) => {
            const row = document.createElement('tr');
            
            if (item.success && item.data) {
                const data = item.data;
                row.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span class="badge bg-success"><i class="fas fa-check"></i></span></td>
                    <td>
                        ${data.thumbnailUrl 
                            ? `<img src="${data.thumbnailUrl}" class="img-thumbnail" style="max-width: 80px; max-height: 60px;" alt="thumbnail" onerror="this.style.display='none'">`
                            : '<span class="text-muted">-</span>'
                        }
                    </td>
                    <td>
                        <div class="text-truncate" style="max-width: 300px;" title="${this.escapeHtml(data.title || '')}">
                            ${this.escapeHtml(data.title || '（タイトルなし）')}
                        </div>
                        <small class="text-muted">
                            <a href="${item.url}" target="_blank" class="text-info">
                                <i class="fas fa-external-link-alt me-1"></i>開く
                            </a>
                        </small>
                    </td>
                    <td>${this.escapeHtml(data.authorName || '-')}</td>
                    <td><code>${data.unique_video_id || '-'}</code></td>
                `;
            } else {
                row.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span class="badge bg-danger"><i class="fas fa-times"></i></span></td>
                    <td colspan="4">
                        <div class="text-danger">
                            <i class="fas fa-exclamation-circle me-1"></i>
                            ${this.escapeHtml(item.error || '取得失敗')}
                        </div>
                        <small class="text-muted">
                            <a href="${item.url}" target="_blank" class="text-info">
                                ${this.escapeHtml(item.url)}
                            </a>
                        </small>
                    </td>
                `;
            }

            this.resultsBody.appendChild(row);
        });

        this.jsonResponse.textContent = JSON.stringify(result, null, 2);

        this.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clearResults() {
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'none';
        this.loadingSection.style.display = 'none';
        this.resultsBody.innerHTML = '';
        this.jsonResponse.textContent = '';
        this.progressBar.style.width = '0%';
        this.progressText.textContent = '';
    }
}

class RecipeExtractorTest {
    constructor() {
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        this.urlInput = document.getElementById('recipeUrlInput');
        this.modelSelect = document.getElementById('geminiModelSelect');
        this.extractBtn = document.getElementById('extractRecipeBtn');
        this.loadingSection = document.getElementById('recipeLoadingSection');
        this.progressText = document.getElementById('recipeProgressText');
        this.errorSection = document.getElementById('recipeErrorSection');
        this.errorMessage = document.getElementById('recipeErrorMessage');
        this.resultsSection = document.getElementById('recipeResultsSection');
        this.extractionMethodBadge = document.getElementById('extractionMethodBadge');
        this.aiModelBadge = document.getElementById('aiModelBadge');
        this.extractionMethodText = document.getElementById('extractionMethodText');
        this.usedModelText = document.getElementById('usedModelText');
        this.tokensUsedText = document.getElementById('tokensUsedText');
        this.inputTokensText = document.getElementById('inputTokensText');
        this.outputTokensText = document.getElementById('outputTokensText');
        this.refinementStatusText = document.getElementById('refinementStatusText');
        this.refinementErrorSection = document.getElementById('refinementErrorSection');
        this.refinementErrorText = document.getElementById('refinementErrorText');
        this.extractionFlowText = document.getElementById('extractionFlowText');
        this.downloadMethodText = document.getElementById('downloadMethodText');
        this.diagnosticsSection = document.getElementById('diagnosticsSection');
        this.diagnosticsText = document.getElementById('diagnosticsText');
        this.recipeTextDisplay = document.getElementById('recipeTextDisplay');
        this.ingredientsList = document.getElementById('ingredientsList');
        this.stepsList = document.getElementById('stepsList');
        this.tipsSection = document.getElementById('tipsSection');
        this.tipsText = document.getElementById('tipsText');
        this.clearBtn = document.getElementById('clearRecipeResults');
    }

    bindEvents() {
        if (this.extractBtn) {
            this.extractBtn.addEventListener('click', () => this.extractRecipe());
        }
        if (this.clearBtn) {
            this.clearBtn.addEventListener('click', () => this.clearResults());
        }
        if (this.urlInput) {
            this.urlInput.addEventListener('input', () => {
                if (this.resultsSection.style.display !== 'none' || 
                    this.errorSection.style.display !== 'none') {
                    this.clearResults();
                }
            });
        }
    }

    async extractRecipe() {
        const url = this.urlInput.value.trim();
        const model = this.modelSelect.value;

        if (!url) {
            this.showError('動画URLを入力してください');
            return;
        }

        try {
            this.showLoading();
            this.progressText.textContent = 'リクエスト送信中...';

            const response = await fetch('/api/test/extract-recipe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    video_url: url,
                    model: model
                })
            });

            this.progressText.textContent = 'レスポンスを処理中...';

            const result = await response.json();

            if (!response.ok || !result.success) {
                throw new Error(result.error || 'レシピ抽出に失敗しました');
            }

            this.displayResults(result);

        } catch (error) {
            console.error('Recipe extraction error:', error);
            this.showError(error.message);
        } finally {
            this.hideLoading();
        }
    }

    showLoading() {
        this.loadingSection.style.display = 'block';
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'none';
        this.extractBtn.disabled = true;
        this.extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>抽出中...';
    }

    hideLoading() {
        this.loadingSection.style.display = 'none';
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-magic me-2"></i>レシピを抽出';
    }

    showError(message) {
        this.errorSection.style.display = 'block';
        this.resultsSection.style.display = 'none';
        this.errorMessage.textContent = message;
    }

    displayResults(result) {
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'block';

        const methodLabels = {
            'description': '説明欄から抽出',
            'comment': '投稿者コメントから抽出',
            'ai_video': 'AI動画解析で抽出'
        };

        const methodColors = {
            'description': 'bg-primary',
            'comment': 'bg-info',
            'ai_video': 'bg-warning text-dark'
        };

        const method = result.extraction_method;
        const methodLabel = methodLabels[method] || method;
        const methodColor = methodColors[method] || 'bg-secondary';

        this.extractionMethodBadge.className = `badge ${methodColor} me-1`;
        this.extractionMethodBadge.textContent = methodLabel;
        
        if (result.ai_model) {
            this.aiModelBadge.textContent = result.ai_model;
            this.aiModelBadge.style.display = 'inline';
        } else {
            this.aiModelBadge.style.display = 'none';
        }

        this.extractionMethodText.textContent = methodLabel;
        this.usedModelText.textContent = result.ai_model || '使用なし';
        this.tokensUsedText.textContent = result.tokens_used ? result.tokens_used.toLocaleString() : '0';
        
        // Display input/output tokens
        if (this.inputTokensText) {
            this.inputTokensText.textContent = result.input_tokens ? result.input_tokens.toLocaleString() : '0';
        }
        if (this.outputTokensText) {
            this.outputTokensText.textContent = result.output_tokens ? result.output_tokens.toLocaleString() : '0';
        }

        // Display extraction flow
        if (this.extractionFlowText) {
            this.extractionFlowText.textContent = result.extraction_flow || '-';
        }

        // Display refinement status
        const refinementStatusLabels = {
            'success': '成功',
            'failed': '失敗',
            'skipped': 'スキップ'
        };
        const refinementStatusColors = {
            'success': 'text-success',
            'failed': 'text-danger',
            'skipped': 'text-muted'
        };
        const refinementStatus = result.refinement_status || 'skipped';
        const statusLabel = refinementStatusLabels[refinementStatus] || refinementStatus;
        const statusColor = refinementStatusColors[refinementStatus] || 'text-info';
        
        if (this.refinementStatusText) {
            this.refinementStatusText.textContent = statusLabel;
            this.refinementStatusText.className = statusColor;
        }
        
        if (this.refinementErrorSection && this.refinementErrorText) {
            if (result.refinement_error && refinementStatus === 'failed') {
                this.refinementErrorSection.style.display = 'block';
                this.refinementErrorText.textContent = result.refinement_error;
            } else {
                this.refinementErrorSection.style.display = 'none';
            }
        }

        // Display download method and diagnostics
        if (this.downloadMethodText) {
            this.downloadMethodText.textContent = result.download_method || '-';
        }
        if (this.diagnosticsSection && this.diagnosticsText) {
            if (result.diagnostics) {
                this.diagnosticsSection.style.display = 'block';
                this.diagnosticsText.textContent = result.diagnostics;
            } else {
                this.diagnosticsSection.style.display = 'none';
            }
        }

        this.recipeTextDisplay.textContent = result.recipe_text;

        // Display structured ingredients
        if (this.ingredientsList) {
            this.ingredientsList.innerHTML = '';
            if (result.ingredients && result.ingredients.length > 0) {
                result.ingredients.forEach(ing => {
                    const li = document.createElement('li');
                    li.className = 'mb-1';
                    if (ing.sub_amount) li.dataset.subAmount = ing.sub_amount;
                    if (ing.sub_unit) li.dataset.subUnit = ing.sub_unit;
                    const nameSpan = `<span class="text-info">${this.escapeHtml(ing.name)}</span>`;
                    let amountPart = '';
                    if (ing.amount && ing.unit) {
                        amountPart = ` <span class="text-muted">${this.escapeHtml(ing.amount)}${this.escapeHtml(ing.unit)}</span>`;
                    } else if (ing.amount) {
                        amountPart = ` <span class="text-muted">${this.escapeHtml(ing.amount)}</span>`;
                    } else if (ing.unit) {
                        amountPart = ` <span class="text-muted">${this.escapeHtml(ing.unit)}</span>`;
                    }
                    let subPart = '';
                    if (ing.sub_amount && ing.sub_unit) {
                        subPart = ` <span class="text-muted small">(${this.escapeHtml(ing.sub_amount)}${this.escapeHtml(ing.sub_unit)})</span>`;
                    }
                    li.innerHTML = nameSpan + amountPart + subPart;
                    this.ingredientsList.appendChild(li);
                });
            } else {
                this.ingredientsList.innerHTML = '<li class="text-muted">材料情報なし</li>';
            }
        }

        // Display structured steps
        if (this.stepsList) {
            this.stepsList.innerHTML = '';
            if (result.steps && result.steps.length > 0) {
                result.steps.forEach(step => {
                    const li = document.createElement('li');
                    li.className = 'mb-2';
                    li.textContent = step;
                    this.stepsList.appendChild(li);
                });
            } else {
                this.stepsList.innerHTML = '<li class="text-muted">手順情報なし</li>';
            }
        }

        // Display tips
        if (this.tipsSection && this.tipsText) {
            if (result.tips) {
                this.tipsSection.style.display = 'block';
                this.tipsText.textContent = result.tips;
            } else {
                this.tipsSection.style.display = 'none';
            }
        }

        this.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clearResults() {
        this.errorSection.style.display = 'none';
        this.resultsSection.style.display = 'none';
        this.loadingSection.style.display = 'none';
        this.recipeTextDisplay.textContent = '';
        if (this.ingredientsList) this.ingredientsList.innerHTML = '';
        if (this.stepsList) this.stepsList.innerHTML = '';
        if (this.tipsSection) this.tipsSection.style.display = 'none';
        if (this.tipsText) this.tipsText.textContent = '';
        if (this.downloadMethodText) this.downloadMethodText.textContent = '-';
        if (this.diagnosticsSection) this.diagnosticsSection.style.display = 'none';
        if (this.diagnosticsText) this.diagnosticsText.textContent = '';
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new MetadataExtractor();
    new CollectionExtractor();
    new RecipeExtractorTest();
    
    // Add some helpful console messages for developers
    console.log('🚀 SNSメタデータ抽出ツールが初期化されました');
    console.log('📚 API ドキュメント:');
    console.log('  POST /api/v2/get-metadata - URLからメタデータを抽出');
    console.log('  POST /api/get-metadata - 旧エンドポイント');
    console.log('  POST /api/extract-collection-metadata - Instagramコレクション抽出');
    console.log('  GET /api/health - ヘルスチェック');
});
