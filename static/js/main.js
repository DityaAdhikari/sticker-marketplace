document.addEventListener('DOMContentLoaded', () => {
  // 1. DOM Element Selectors
  const navItems = document.querySelectorAll('.nav-item');
  const mobileToggle = document.getElementById('mobile-toggle');
  const navLinksContainer = document.getElementById('nav-links-container');
  const actionItems = document.querySelectorAll('.action-item');

  // 2. Active State Link Handler
  navItems.forEach(item => {
    item.addEventListener('click', () => {
      // If it's a dropdown menu container, let CSS or another logic handle it
      if (item.classList.contains('dropdown')) return;
      
      // Remove 'active' highlight from all items, then add to the clicked item
      navItems.forEach(nav => nav.classList.remove('active'));
      item.classList.add('active');
      
      // Auto-collapse mobile menu after selection
      if (navLinksContainer.classList.contains('show')) {
        toggleMobileMenu();
      }
    });
  });

  // 3. Mobile Menu Toggle Logic
  function toggleMobileMenu() {
    navLinksContainer.classList.toggle('show');
    
    // Switch the hamburger icon to an "X" close icon dynamically
    const icon = mobileToggle.querySelector('i');
    if (navLinksContainer.classList.contains('show')) {
      icon.className = 'fa-solid fa-xmark';
    } else {
      icon.className = 'fa-solid fa-bars';
    }
  }

  if (mobileToggle && navLinksContainer) {
    mobileToggle.addEventListener('click', toggleMobileMenu);
  }

  // 4. E-commerce Action Click Listeners (Wishlist, Cart, Login)
  actionItems.forEach(action => {
    action.addEventListener('click', () => {
      const labelElement = action.querySelector('.action-label');
      const label = labelElement ? labelElement.textContent : 'Action';
      console.log(`${label} button clicked.`);
      // Future feature hooks (e.g., openCartModal(), redirectToLogin()) can go here
    });
  });
});
//feature 
document.addEventListener('DOMContentLoaded', () => {
  // Select all individual product item cart trigger targets
  const cartButtons = document.querySelectorAll('.add-to-cart-btn');

  // Interactive Click Handlers
  cartButtons.forEach(button => {
    button.addEventListener('click', (event) => {
      // Stop layout events bubble propagation cleanly 
      event.stopPropagation();

      // Retrieve item metadata reference context details safely
      const card = button.closest('.sticker-card');
      const stickerId = card.getAttribute('data-id');
      const stickerTitle = card.querySelector('.sticker-title').textContent;
      const stickerPrice = card.querySelector('.price-tag').textContent;

      // Log dispatch callback simulation data
      console.log(`[Basket Dispatch]: Adding Item ID ${stickerId} (${stickerTitle}) priced at ${stickerPrice} to cart pipeline state.`);
      
      // Visual feedback transition indicator logic animation hook helper
      triggerButtonFeedback(button);
    });
  });

  // Short animation feedback change state handler execution loop
  function triggerButtonFeedback(buttonElement) {
    const icon = buttonElement.querySelector('i');
    
    // Temporarily exchange icon representations
    icon.className = 'fa-solid fa-check';
    buttonElement.style.backgroundColor = '#2e7d32'; // Green success color
    buttonElement.style.borderColor = '#2e7d32';
    buttonElement.style.color = '#ffffff';

    setTimeout(() => {
      // Revert states cleanly back to default values
      icon.className = 'fa-solid fa-cart-plus';
      buttonElement.style.backgroundColor = '';
      buttonElement.style.borderColor = '';
      buttonElement.style.color = '';
    }, 1200);
  }
});

