/**
 * ComicVault - Main JavaScript File
 * Handles notifications, UI interactions, and AJAX requests
 */

// ============================================
// NOTIFICATION SYSTEM
// ============================================

function showNotification(message, type = 'info', duration = 3000) {
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(n => n.remove());
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span class="notification-message">${message}</span>
        <button class="notification-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    
    document.body.appendChild(notification);
    setTimeout(() => notification.classList.add('show'), 10);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, duration);
}

window.showToast = showNotification; // Alias for compatibility

// ============================================
// LAZY LOADING IMAGES
// ============================================

// Initialize lazy loading with Intersection Observer
document.addEventListener('DOMContentLoaded', () => {
    initLazyLoading();
    initFocusManagement();
});

function initLazyLoading() {
    // Check if IntersectionObserver is supported
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    
                    // Load the actual image
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                    }
                    
                    // Load srcset if available
                    if (img.dataset.srcset) {
                        img.srcset = img.dataset.srcset;
                        img.removeAttribute('data-srcset');
                    }
                    
                    // Remove lazy class and blur placeholder
                    img.classList.remove('lazy-image');
                    img.classList.add('loaded');
                    
                    // Stop observing this image
                    observer.unobserve(img);
                }
            });
        }, {
            rootMargin: '50px 0px', // Start loading 50px before entering viewport
            threshold: 0.01
        });
        
        // Observe all lazy images
        document.querySelectorAll('img.lazy-image').forEach(img => {
            imageObserver.observe(img);
        });
    } else {
        // Fallback for browsers without IntersectionObserver
        document.querySelectorAll('img.lazy-image').forEach(img => {
            if (img.dataset.src) {
                img.src = img.dataset.src;
                img.classList.remove('lazy-image');
            }
        });
    }
}

// Function to lazy load images in dynamically added content
window.initLazyLoading = initLazyLoading;

// ============================================
// ACCESSIBILITY - FOCUS MANAGEMENT
// ============================================

function initFocusManagement() {
    // Add focus-visible class for keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            document.body.classList.add('keyboard-navigation');
        }
    });
    
    document.addEventListener('mousedown', () => {
        document.body.classList.remove('keyboard-navigation');
    });
    
    // Handle skip to content link
    const skipLink = document.querySelector('.skip-to-content');
    if (skipLink) {
        skipLink.addEventListener('click', (e) => {
            e.preventDefault();
            const mainContent = document.getElementById('main-content');
            if (mainContent) {
                mainContent.focus();
                mainContent.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }
}

// Trap focus within modals
window.trapFocus = function(element) {
    const focusableElements = element.querySelectorAll(
        'a[href], button, textarea, input[type="text"], input[type="radio"], input[type="checkbox"], select'
    );
    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];
    
    element.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            if (e.shiftKey) {
                if (document.activeElement === firstFocusable) {
                    lastFocusable.focus();
                    e.preventDefault();
                }
            } else {
                if (document.activeElement === lastFocusable) {
                    firstFocusable.focus();
                    e.preventDefault();
                }
            }
        }
        
        if (e.key === 'Escape') {
            // Close modal on Escape
            const closeBtn = element.querySelector('[data-dismiss="modal"], .close, .btn-close');
            if (closeBtn) closeBtn.click();
        }
    });
};

// ============================================
// SERVICE WORKER & PERFORMANCE
// ============================================

// Register service worker
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/js/sw.js')
            .then(registration => {
                console.log('SW registered: ', registration);
                
                // Check for updates periodically
                setInterval(() => {
                    registration.update();
                }, 60 * 60 * 1000); // Check every hour
            })
            .catch(registrationError => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}

// Lazy Loading Images
function setupLazyLoading() {
    initLazyLoading();
}

// Blur-up placeholders
function setupBlurUpPlaceholders() {
    const images = document.querySelectorAll('img[data-blur-url]');
    
    images.forEach(img => {
        // Set blur placeholder first
        const blurImg = new Image();
        blurImg.src = img.dataset.blurUrl;
        blurImg.onload = () => {
            img.style.backgroundImage = `url(${img.dataset.blurUrl})`;
            img.classList.add('blur-up');
        };
        
        // Load full image
        const fullImg = new Image();
        fullImg.src = img.src;
        fullImg.onload = () => {
            img.style.backgroundImage = `url(${img.src})`;
            img.classList.add('loaded');
        };
    });
}

// Focus Management
function setupFocusManagement() {
    // Skip to content link
    const skipLink = document.createElement('a');
    skipLink.href = '#main-content';
    skipLink.className = 'skip-link';
    skipLink.textContent = 'Skip to content';
    document.body.insertBefore(skipLink, document.body.firstChild);
    
    // Main content target
    const mainContent = document.querySelector('main, .main-content');
    if (mainContent) {
        mainContent.id = 'main-content';
    }
    
    // Focus trap for modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            const modal = document.querySelector('.modal.show');
            if (modal) {
                trapFocus(e, modal);
            }
        }
    });
}

function trapFocus(e, container) {
    const focusableElements = container.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    
    if (e.shiftKey) {
        if (document.activeElement === firstElement) {
            lastElement.focus();
            e.preventDefault();
        }
    } else {
        if (document.activeElement === lastElement) {
            firstElement.focus();
            e.preventDefault();
        }
    }
}

// Offline indicator
function setupOfflineIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'offline-indicator';
    indicator.innerHTML = `
        <span>You're offline. Some features may be limited.</span>
    `;
    document.body.appendChild(indicator);
    
    window.addEventListener('online', () => {
        indicator.classList.remove('show');
        showNotification('Back online!', 'success');
    });
    
    window.addEventListener('offline', () => {
        indicator.classList.add('show');
        showNotification('You\'re offline. Showing cached content.', 'warning');
    });
}

// Initialize performance features
document.addEventListener('DOMContentLoaded', () => {
    setupLazyLoading();
    setupBlurUpPlaceholders();
    setupFocusManagement();
    setupOfflineIndicator();
    enhanceAccessibility();
});

// Re-run enhancements when content changes
const observer = new MutationObserver(() => {
    enhanceAccessibility();
    setupLazyLoading();
});

observer.observe(document.body, {
    childList: true,
    subtree: true
});

// ============================================
// LIBRARY & FAVORITES
// ============================================

async function toggleLibrary(comicId) {
    try {
        const response = await fetch('/api/toggle_library', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comic_id: comicId })
        });
        
        if (response.status === 401) {
            window.location.href = '/login';
            return;
        }
        
        const data = await response.json();
        if (data.success) {
            const btn = document.querySelector(`[data-comic-id="${comicId}"].library-btn`);
            if (btn) {
                btn.classList.toggle('in-library', data.in_library);
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.className = data.in_library ? 'fas fa-heart' : 'far fa-heart';
                }
            }
            showNotification(data.message, 'success');
        } else {
            showNotification(data.error || 'Error updating library', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('An error occurred', 'error');
    }
}

// ============================================
// RATING SYSTEM
// ============================================

async function submitRating(comicId, score) {
    try {
        const response = await fetch('/api/rate_comic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comic_id: comicId, score: score })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('Rating saved!', 'success');
            // Update UI if elements exist
            const avgEl = document.querySelector('.average-rating');
            if (avgEl) avgEl.textContent = data.new_average;
            const countEl = document.querySelector('.rating-count');
            if (countEl) countEl.textContent = `(${data.total_ratings} ratings)`;
        } else {
            showNotification(data.error || 'Error saving rating', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Failed to save rating', 'error');
    }
}

// ============================================
// ARIA ENHANCEMENTS
// ============================================

// Add ARIA labels dynamically
function enhanceAccessibility() {
    // Add aria-label to comic cards
    document.querySelectorAll('.comic-card').forEach(card => {
        const title = card.querySelector('.comic-title')?.textContent || '';
        const author = card.querySelector('.comic-author')?.textContent || '';
        if (!card.getAttribute('aria-label')) {
            card.setAttribute('aria-label', `${title} by ${author}`);
        }
    });
    
    // Add aria-describedby to modals
    document.querySelectorAll('.modal').forEach(modal => {
        const title = modal.querySelector('.modal-title');
        if (title && !modal.getAttribute('aria-labelledby')) {
            modal.setAttribute('aria-labelledby', title.id || `modal-title-${Date.now()}`);
            if (!title.id) {
                title.id = `modal-title-${Date.now()}`;
            }
        }
    });
    
    // Add role to navigation
    document.querySelectorAll('nav').forEach(nav => {
        if (!nav.getAttribute('role')) {
            nav.setAttribute('role', 'navigation');
        }
    });
    
    // Add aria-live to notifications
    document.querySelectorAll('.notification').forEach(notification => {
        notification.setAttribute('aria-live', 'polite');
    });
}

// ============================================
// READING PROGRESS
// ============================================

async function saveReadingProgress(comicId, page, total) {
    try {
        await fetch('/api/reading_progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                comic_id: comicId, 
                current_page: page,
                total_pages: total
            })
        });
    } catch (error) {
        console.error('Error saving progress:', error);
    }
}

// ============================================
// UI INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    // Star Rating Interactivity
    const stars = document.querySelectorAll('.star-rating .star');
    stars.forEach(star => {
        star.addEventListener('click', async () => {
            const container = star.parentElement;
            const comicId = container.dataset.comicId;
            const score = star.dataset.value;
            if (comicId && score) {
                await submitRating(comicId, score);
                // Update stars visual
                const allStars = container.querySelectorAll('.star');
                allStars.forEach(s => {
                    s.classList.toggle('fas', s.dataset.value <= score);
                    s.classList.toggle('far', s.dataset.value > score);
                });
            }
        });
    });

    // Library Toggle Buttons
    const libBtns = document.querySelectorAll('.library-btn');
    libBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const comicId = btn.dataset.comicId;
            if (comicId) toggleLibrary(comicId);
        });
    });
});

// ============================================
// SEARCH HISTORY (localStorage)
// ============================================

const SEARCH_HISTORY_KEY = 'comic_search_history';
const MAX_HISTORY_ITEMS = 10;

function getSearchHistory() {
    try {
        const history = localStorage.getItem(SEARCH_HISTORY_KEY);
        return history ? JSON.parse(history) : [];
    } catch (e) {
        return [];
    }
}

function addToSearchHistory(query) {
    if (!query || query.trim().length < 2) return;
    
    const history = getSearchHistory();
    const cleanQuery = query.trim();
    
    // Remove if already exists
    const filtered = history.filter(item => item.toLowerCase() !== cleanQuery.toLowerCase());
    
    // Add to front
    filtered.unshift(cleanQuery);
    
    // Limit size
    const limited = filtered.slice(0, MAX_HISTORY_ITEMS);
    
    try {
        localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(limited));
    } catch (e) {
        console.error('Error saving search history:', e);
    }
}

function clearSearchHistory() {
    try {
        localStorage.removeItem(SEARCH_HISTORY_KEY);
    } catch (e) {
        console.error('Error clearing search history:', e);
    }
}

function renderSearchHistory(containerId, onSelect) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    const history = getSearchHistory();
    if (history.length === 0) {
        container.style.display = 'none';
        return;
    }
    
    container.innerHTML = `
        <div class="search-history-header">
            <span>Recent Searches</span>
            <button type="button" class="clear-history" onclick="ComicVault.clearSearchHistory(); this.closest('.search-history').style.display='none';">
                Clear
            </button>
        </div>
        ${history.map(q => `
            <div class="search-history-item" data-query="${escapeHtml(q)}">
                <i class="far fa-clock"></i>
                <span>${escapeHtml(q)}</span>
            </div>
        `).join('')}
    `;
    
    container.style.display = 'block';
    
    // Add click handlers
    container.querySelectorAll('.search-history-item').forEach(item => {
        item.addEventListener('click', () => {
            const query = item.dataset.query;
            onSelect(query);
            container.style.display = 'none';
        });
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Export to window
window.showNotification = showNotification;
window.toggleLibrary = toggleLibrary;
window.submitRating = submitRating;
window.saveReadingProgress = saveReadingProgress;
window.getSearchHistory = getSearchHistory;
window.addToSearchHistory = addToSearchHistory;
window.clearSearchHistory = clearSearchHistory;
window.renderSearchHistory = renderSearchHistory;
window.ComicVault = { getSearchHistory, addToSearchHistory, clearSearchHistory, renderSearchHistory, showToast: showNotification };

// ============================================
// BLUR-UP IMAGE LOADING
// ============================================

/**
 * Initialize blur-up loading for images with data-src attribute
 * Shows a blurred placeholder while the full image loads
 */
function initBlurUpLoading() {
    const containers = document.querySelectorAll('.image-container[data-src]');
    
    containers.forEach(container => {
        const img = container.querySelector('img[data-src]');
        const placeholder = container.querySelector('.image-placeholder');
        
        if (!img) return;
        
        // Create placeholder if it doesn't exist
        if (!placeholder && img.dataset.placeholder) {
            const newPlaceholder = document.createElement('div');
            newPlaceholder.className = 'image-placeholder';
            newPlaceholder.style.backgroundImage = `url(${img.dataset.placeholder})`;
            container.insertBefore(newPlaceholder, img);
        }
        
        // Load full image
        const fullSrc = img.dataset.src;
        const fullImg = new Image();
        
        fullImg.onload = () => {
            img.src = fullSrc;
            img.classList.add('loaded');
            
            // Fade out placeholder
            const ph = container.querySelector('.image-placeholder');
            if (ph) {
                ph.classList.add('loaded');
                setTimeout(() => ph.remove(), 300);
            }
        };
        
        fullImg.onerror = () => {
            // Show error state
            container.classList.add('image-error');
        };
        
        fullImg.src = fullSrc;
    });
}

// Skeleton loading for comic cards
function createSkeletonCard() {
    const card = document.createElement('div');
    card.className = 'comic-card comic-card-skeleton';
    card.innerHTML = `
        <div class="skeleton skeleton-image"></div>
        <div class="comic-card-content">
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-author"></div>
        </div>
    `;
    return card;
}

// Show skeleton loading state
function showSkeletonLoading(container, count = 6) {
    container.innerHTML = '';
    for (let i = 0; i < count; i++) {
        container.appendChild(createSkeletonCard());
    }
}

// Hide skeleton loading and show actual content
function hideSkeletonLoading(container, content) {
    container.innerHTML = '';
    if (typeof content === 'string') {
        container.innerHTML = content;
    } else if (content instanceof Node) {
        container.appendChild(content);
    }
}

// Initialize blur-up on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initBlurUpLoading();
});

// Export blur-up functions
window.initBlurUpLoading = initBlurUpLoading;
window.createSkeletonCard = createSkeletonCard;
window.showSkeletonLoading = showSkeletonLoading;
window.hideSkeletonLoading = hideSkeletonLoading;
