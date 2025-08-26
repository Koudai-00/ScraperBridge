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

        // Control elements
        this.clearResults = document.getElementById('clearResults');
        this.exampleUrlButtons = document.querySelectorAll('.example-url');
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
    }

    async extractMetadata() {
        const url = this.urlInput.value.trim();
        
        if (!url) {
            this.showError('Please enter a valid URL');
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
            this.showError(`Failed to extract metadata: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    showLoading() {
        this.loadingSection.style.display = 'block';
        this.resultsSection.style.display = 'none';
        this.errorSection.style.display = 'none';
        this.extractBtn.disabled = true;
        this.extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processing...';
    }

    hideLoading() {
        this.loadingSection.style.display = 'none';
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-magic me-2"></i>Extract Metadata';
    }

    displayResults(metadata) {
        // Show results section
        this.resultsSection.style.display = 'block';
        this.errorSection.style.display = 'none';

        // Update platform badge
        this.updatePlatformBadge(metadata.platform);

        // Update metadata displays
        this.titleDisplay.textContent = metadata.title || 'Not available';
        this.authorDisplay.textContent = metadata.authorName || 'Not available';
        this.videoIdDisplay.textContent = metadata.unique_video_id || 'Not available';

        // Update thumbnail
        this.updateThumbnail(metadata.thumbnailUrl);

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
            other: { 
                icon: 'fas fa-question', 
                text: 'Unknown',
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

    truncateUrl(url, maxLength = 50) {
        if (url.length <= maxLength) return url;
        return url.substring(0, maxLength - 3) + '...';
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

        // Reset displays
        this.platformBadge.className = 'badge bg-info fs-6';
        this.platformBadge.innerHTML = '<i class="fas fa-tag me-1"></i>Platform';
        this.titleDisplay.textContent = '-';
        this.authorDisplay.textContent = '-';
        this.videoIdDisplay.textContent = '-';
        this.jsonResponse.textContent = 'No data';
        
        // Reset thumbnail
        this.showThumbnailPlaceholder();
        
        // Reset button
        this.extractBtn.disabled = false;
        this.extractBtn.innerHTML = '<i class="fas fa-magic me-2"></i>Extract Metadata';
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new MetadataExtractor();
    
    // Add some helpful console messages for developers
    console.log('🚀 SNS Metadata Extractor initialized');
    console.log('📚 API Documentation:');
    console.log('  POST /api/v2/get-metadata - Extract metadata from URLs');
    console.log('  POST /api/get-metadata - Legacy endpoint');
    console.log('  GET /api/health - Health check');
});
