/**
 * ComicVault - Bottom Sheet Navigation Controller
 * Phase 2, Week 1 Implementation
 * Features: Swipe gestures, smooth animations, accessibility
 */

class BottomNavController {
    constructor() {
        this.sheet = null;
        this.handle = null;
        this.content = null;
        this.overlay = null;
        this.isOpen = false;
        this.startY = 0;
        this.currentY = 0;
        this.sheetHeight = 0;
        this.threshold = 100; // Minimum swipe to trigger action
        
        this.init();
    }

    init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    setup() {
        this.sheet = document.getElementById('bottom-sheet');
        this.handle = document.getElementById('bottom-sheet-handle');
        this.content = document.getElementById('bottom-sheet-content');
        this.overlay = document.getElementById('bottom-sheet-overlay');

        if (!this.sheet) {
            console.warn('Bottom sheet element not found');
            return;
        }

        this.bindEvents();
        this.setupAccessibility();
    }

    bindEvents() {
        // Touch events for mobile
        this.handle.addEventListener('touchstart', (e) => this.handleTouchStart(e), { passive: true });
        this.handle.addEventListener('touchmove', (e) => this.handleTouchMove(e), { passive: true });
        this.handle.addEventListener('touchend', (e) => this.handleTouchEnd(e), { passive: true });

        // Mouse events for desktop
        this.handle.addEventListener('mousedown', (e) => this.handleMouseDown(e));
        
        // Click events
        this.handle.addEventListener('click', () => this.toggle());
        this.overlay.addEventListener('click', () => this.close());

        // Keyboard events
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });

        // Navigation items
        const navItems = this.sheet.querySelectorAll('.bottom-nav-item');
        navItems.forEach(item => {
            item.addEventListener('click', (e) => this.handleNavClick(e, item));
        });

        // Prevent scrolling when sheet is open
        this.sheet.addEventListener('touchmove', (e) => {
            if (this.isOpen) {
                e.stopPropagation();
            }
        }, { passive: false });
    }

    setupAccessibility() {
        // ARIA labels and roles
        this.sheet.setAttribute('role', 'dialog');
        this.sheet.setAttribute('aria-label', 'Navigation menu');
        this.sheet.setAttribute('aria-hidden', 'true');
        
        this.handle.setAttribute('role', 'button');
        this.handle.setAttribute('aria-expanded', 'false');
        this.handle.setAttribute('tabindex', '0');

        // Handle keyboard activation
        this.handle.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.toggle();
            }
        });
    }

    // Touch handlers
    handleTouchStart(e) {
        this.startY = e.touches[0].clientY;
        this.sheetHeight = this.sheet.offsetHeight;
        this.sheet.style.transition = 'none';
    }

    handleTouchMove(e) {
        if (!this.startY) return;
        
        this.currentY = e.touches[0].clientY;
        const deltaY = this.currentY - this.startY;
        
        // Only allow dragging in certain directions
        if (this.isOpen && deltaY > 0) {
            // Dragging down when open
            this.sheet.style.transform = `translateY(${deltaY}px)`;
        } else if (!this.isOpen && deltaY < 0) {
            // Dragging up when closed
            const progress = Math.min(Math.abs(deltaY) / this.sheetHeight, 1);
            this.sheet.style.transform = `translateY(${(1 - progress) * 100}%)`;
        }
    }

    handleTouchEnd(e) {
        if (!this.startY) return;
        
        const deltaY = this.currentY - this.startY;
        this.sheet.style.transition = 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
        
        if (this.isOpen && deltaY > this.threshold) {
            this.close();
        } else if (!this.isOpen && deltaY < -this.threshold) {
            this.open();
        } else {
            // Snap back to current state
            this.isOpen ? this.open() : this.close();
        }
        
        this.startY = 0;
        this.currentY = 0;
    }

    // Mouse handlers (for desktop)
    handleMouseDown(e) {
        this.startY = e.clientY;
        this.sheetHeight = this.sheet.offsetHeight;
        this.sheet.style.transition = 'none';

        const handleMouseMove = (e) => {
            this.currentY = e.clientY;
            const deltaY = this.currentY - this.startY;
            
            if (this.isOpen && deltaY > 0) {
                this.sheet.style.transform = `translateY(${deltaY}px)`;
            }
        };

        const handleMouseUp = () => {
            const deltaY = this.currentY - this.startY;
            this.sheet.style.transition = 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
            
            if (this.isOpen && deltaY > this.threshold) {
                this.close();
            } else {
                this.isOpen ? this.open() : this.close();
            }
            
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            this.startY = 0;
            this.currentY = 0;
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }

    // State management
    open() {
        this.isOpen = true;
        this.sheet.classList.add('open');
        this.sheet.style.transform = 'translateY(0)';
        this.overlay.classList.add('visible');
        this.handle.setAttribute('aria-expanded', 'true');
        this.sheet.setAttribute('aria-hidden', 'false');
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
        
        // Haptic feedback on mobile
        if (navigator.vibrate && window.matchMedia('(pointer: coarse)').matches) {
            navigator.vibrate(10);
        }

        // Dispatch event
        this.dispatchEvent('bottomnav:open');
    }

    close() {
        this.isOpen = false;
        this.sheet.classList.remove('open');
        this.sheet.style.transform = 'translateY(calc(100% - 60px))';
        this.overlay.classList.remove('visible');
        this.handle.setAttribute('aria-expanded', 'false');
        this.sheet.setAttribute('aria-hidden', 'true');
        
        // Restore body scroll
        document.body.style.overflow = '';

        // Dispatch event
        this.dispatchEvent('bottomnav:close');
    }

    toggle() {
        this.isOpen ? this.close() : this.open();
    }

    handleNavClick(e, item) {
        const href = item.getAttribute('href');
        const action = item.dataset.action;

        if (action) {
            e.preventDefault();
            this.handleAction(action);
        }

        // Add active state
        this.sheet.querySelectorAll('.bottom-nav-item').forEach(i => {
            i.classList.remove('active');
        });
        item.classList.add('active');

        // Close sheet on mobile after navigation
        if (window.innerWidth < 768) {
            setTimeout(() => this.close(), 150);
        }
    }

    handleAction(action) {
        switch(action) {
            case 'search':
                this.dispatchEvent('bottomnav:search');
                break;
            case 'library':
                this.dispatchEvent('bottomnav:library');
                break;
            case 'profile':
                this.dispatchEvent('bottomnav:profile');
                break;
            case 'home':
                this.dispatchEvent('bottomnav:home');
                break;
            default:
                console.log('Unknown action:', action);
        }
    }

    dispatchEvent(name) {
        const event = new CustomEvent(name, {
            detail: { controller: this }
        });
        document.dispatchEvent(event);
    }

    // Public API
    setActiveItem(selector) {
        this.sheet.querySelectorAll('.bottom-nav-item').forEach(item => {
            item.classList.remove('active');
            if (item.matches(selector)) {
                item.classList.add('active');
            }
        });
    }

    destroy() {
        this.close();
        // Remove event listeners would go here
        // For now, just hide the sheet
        this.sheet.style.display = 'none';
    }
}

// Initialize on load
window.bottomNavController = new BottomNavController();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BottomNavController;
}
