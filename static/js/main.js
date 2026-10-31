// Lets CSS hide lazy images until they load; without JS they show normally.
document.documentElement.classList.add('js');

document.addEventListener('DOMContentLoaded', () => {
  // Product images: fade each lazy-loaded image in once it arrives
  function initLazyImages(root = document) {
    root.querySelectorAll('img.lazy-img:not(.is-loaded)').forEach((img) => {
      const show = () => img.classList.add('is-loaded');
      if (img.complete) {
        show();
      } else {
        img.addEventListener('load', show, { once: true });
        img.addEventListener('error', show, { once: true });
      }
    });
  }
  initLazyImages();

  // Shop on phones: scroll the category chip row so the current one is visible
  const activeChip = document.querySelector('.shop-cat.active');
  const chipRow = activeChip?.closest('.shop-cats');
  if (chipRow && chipRow.scrollWidth > chipRow.clientWidth) {
    chipRow.scrollLeft = activeChip.offsetLeft - (chipRow.clientWidth - activeChip.offsetWidth) / 2;
  }

  // Shop: load the next batch of stickers as the bottom comes into view.
  // Without JavaScript (or if a fetch fails) the "Load more" link is shown.
  const shopGrid = document.getElementById('shop-grid');
  const shopLoader = document.getElementById('shop-loader');
  if (shopGrid && shopLoader && 'IntersectionObserver' in window) {
    let nextPage = shopGrid.dataset.nextPage;
    let loading = false;

    const observer = new IntersectionObserver(async ([entry]) => {
      if (!entry.isIntersecting || loading || !nextPage) return;
      loading = true;
      try {
        const response = await fetch(`${nextPage}&partial=1`, { credentials: 'same-origin' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const holder = document.createElement('div');
        holder.innerHTML = await response.text();
        const cards = [...holder.children];
        shopGrid.append(...cards);
        cards.forEach((card) => initLazyImages(card));
        nextPage = response.headers.get('X-Next-Page') || '';
        shopLoader.querySelector('a').href = nextPage;
        if (!nextPage) {
          observer.disconnect();
          shopLoader.remove();
        }
      } catch (error) {
        console.error('Could not load more stickers:', error);
        observer.disconnect();
        shopLoader.classList.add('failed');
      } finally {
        loading = false;
      }
    }, { rootMargin: '600px 0px' });

    observer.observe(shopLoader);
  }

  // Heart button: like / unlike (add to / remove from wishlist) on click,
  // without reloading the page. Without JavaScript the form posts normally.
  const likeStatus = document.createElement('p');
  likeStatus.className = 'visually-hidden';
  likeStatus.setAttribute('role', 'status');
  document.body.appendChild(likeStatus);

  function renderLike(button, liked, count) {
    const name = button.dataset.name;
    const label = count === 1 ? 'like' : 'likes';
    button.classList.toggle('liked', liked);
    button.setAttribute('aria-pressed', String(liked));
    button.title = liked ? 'Remove from wishlist' : 'Add to wishlist';
    button.setAttribute('aria-label', `${liked ? `Remove ${name} from` : `Add ${name} to`} wishlist (${count} ${label})`);
    button.querySelector('i').className = `${liked ? 'fa-solid' : 'fa-regular'} fa-heart`;
    button.querySelector('span').textContent = count;
  }

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('.pc-like-form');
    if (!form) return;
    event.preventDefault();

    const button = form.querySelector('.pc-like-btn');
    if (button.disabled) return;
    button.disabled = true;

    try {
      const response = await fetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'fetch', Accept: 'application/json' },
        credentials: 'same-origin',
      });

      if (response.status === 401) {
        window.location.href = (await response.json()).login_url;
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const { liked, count } = await response.json();
      // Keep every heart for this sticker in sync (it can appear more than once)
      document.querySelectorAll(`.pc-like-form[data-sticker-id="${form.dataset.stickerId}"] .pc-like-btn`)
        .forEach((btn) => renderLike(btn, liked, count));

      button.classList.remove('pop');
      void button.offsetWidth; // restart the animation
      if (liked) button.classList.add('pop');
      likeStatus.textContent = `${button.dataset.name} ${liked ? 'added to' : 'removed from'} your wishlist.`;

      // On the profile page, an unliked sticker leaves the Wishlist section
      const wishlistGrid = form.closest('.wishlist-grid');
      if (wishlistGrid && !liked) {
        form.closest('.product-card').remove();
        const counter = document.getElementById('wishlist-count');
        if (counter) counter.textContent = Math.max(0, Number(counter.textContent) - 1);
        if (!wishlistGrid.querySelector('.product-card')) {
          wishlistGrid.hidden = true;
          document.querySelector('.wishlist-empty')?.removeAttribute('hidden');
        }
      }
    } catch (error) {
      console.error('Like failed, falling back to a normal form post:', error);
      form.submit();
    } finally {
      button.disabled = false;
    }
  });

  // Sticker forms: extra-photo picker. Each pick adds to the list (several
  // files at once is fine), shows previews, and is capped at the slot limit.
  // The chosen files are written back into the real <input> for the submit.
  document.querySelectorAll('.photo-picker').forEach((picker) => {
    const max = Number(picker.dataset.max);
    const input = picker.querySelector('input[type=file]');
    const grid = picker.querySelector('[data-photo-grid]');
    const addButton = picker.querySelector('[data-photo-add]');
    const addLabel = picker.querySelector('[data-photo-add-label]');
    const counter = picker.querySelector('[data-photo-count]');
    const message = picker.querySelector('[data-photo-msg]');
    const allowed = ['image/png', 'image/jpeg', 'image/webp'];
    const canAccumulate = typeof DataTransfer === 'function';
    let pending = [];

    const kept = () => [...picker.querySelectorAll('input[name=remove_photo]')].filter((box) => !box.checked).length;
    const free = () => max - kept() - pending.length;

    function render(note = '') {
      if (canAccumulate) {
        const transfer = new DataTransfer();
        pending.forEach((item) => transfer.items.add(item.file));
        input.files = transfer.files;
      }

      grid.querySelectorAll('.extra-photo.pending').forEach((card) => card.remove());
      pending.forEach((item, index) => {
        const card = document.createElement('div');
        card.className = 'extra-photo pending';
        const img = document.createElement('img');
        img.src = item.url;
        img.alt = `New photo: ${item.file.name}`;
        const tag = document.createElement('span');
        tag.className = 'extra-photo-tag';
        tag.textContent = 'New';
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'extra-photo-x';
        remove.dataset.index = index;
        remove.setAttribute('aria-label', `Don't add ${item.file.name}`);
        remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        card.append(img, tag, remove);
        grid.appendChild(card);
      });

      grid.hidden = !grid.children.length;
      counter.textContent = Math.min(max, kept() + pending.length);
      const left = free();
      addButton.disabled = left <= 0;
      addLabel.textContent = left > 0 ? `Add photos (${left} left)` : 'All photo slots used';
      message.textContent = left < 0
        ? `That's ${-left} more than the ${max}-photo limit. Remove some, or untick Remove on a photo you want to keep out.`
        : note;
    }

    addButton.addEventListener('click', () => input.click());

    input.addEventListener('change', () => {
      const picked = [...input.files];
      if (!canAccumulate) {
        // Older browser: a single pick replaces the selection
        pending = picked.slice(0, Math.max(0, max - kept())).map((file) => ({ file, url: URL.createObjectURL(file) }));
        render();
        return;
      }

      const images = picked.filter((file) => allowed.includes(file.type));
      const fresh = images.filter((file) => !pending.some(({ file: p }) =>
        p.name === file.name && p.size === file.size && p.lastModified === file.lastModified));
      const room = Math.max(0, max - kept() - pending.length);
      const added = fresh.slice(0, room);
      added.forEach((file) => pending.push({ file, url: URL.createObjectURL(file) }));

      const notes = [];
      if (fresh.length > added.length) notes.push(`Only ${max} photos fit, so ${fresh.length - added.length} weren't added.`);
      if (images.length < picked.length) notes.push('Some files were skipped: use PNG, JPG or WebP.');
      render(notes.join(' '));
    });

    grid.addEventListener('click', (event) => {
      const remove = event.target.closest('.extra-photo-x');
      if (!remove) return;
      const [item] = pending.splice(Number(remove.dataset.index), 1);
      URL.revokeObjectURL(item.url);
      render();
      addButton.focus();
    });

    // Ticking Remove on a saved photo frees its slot straight away
    grid.addEventListener('change', (event) => {
      if (event.target.name === 'remove_photo') render();
    });

    render();
  });

  // Sticker page: thumbnails, full-size viewer and checkout notice
  const lightbox = document.getElementById('pd-lightbox');
  if (lightbox) {
    const gallery = JSON.parse(lightbox.dataset.gallery || '[]');
    const mainImg = document.getElementById('pd-main-img');
    const boxImg = document.getElementById('pd-lightbox-img');
    const boxCount = document.getElementById('pd-lightbox-count');
    const thumbs = [...document.querySelectorAll('.pd-thumb')];
    let current = 0;

    const show = (index) => {
      current = (index + gallery.length) % gallery.length;
      mainImg.src = gallery[current];
      boxImg.src = gallery[current];
      if (boxCount) boxCount.textContent = `${current + 1} / ${gallery.length}`;
      thumbs.forEach((thumb, i) => {
        thumb.classList.toggle('active', i === current);
        thumb.setAttribute('aria-pressed', String(i === current));
      });
    };

    thumbs.forEach((thumb) => thumb.addEventListener('click', () => show(Number(thumb.dataset.index))));

    document.getElementById('pd-main').addEventListener('click', () => {
      boxImg.src = gallery[current];
      lightbox.showModal();
    });

    lightbox.querySelector('[data-lightbox-close]').addEventListener('click', () => lightbox.close());
    lightbox.querySelectorAll('[data-lightbox-step]').forEach((button) => {
      button.addEventListener('click', () => show(current + Number(button.dataset.lightboxStep)));
    });

    // Click on the dark backdrop (outside the photo and buttons) closes it
    lightbox.addEventListener('click', (event) => {
      if (event.target === lightbox) lightbox.close();
    });

    lightbox.addEventListener('keydown', (event) => {
      if (gallery.length < 2) return;
      if (event.key === 'ArrowRight') show(current + 1);
      if (event.key === 'ArrowLeft') show(current - 1);
    });
  }

  const checkoutNote = document.getElementById('pd-checkout-note');
  document.querySelectorAll('[data-checkout-soon]').forEach((button) => {
    button.addEventListener('click', () => {
      if (checkoutNote) checkoutNote.hidden = false;
    });
  });

  // Follow / unfollow an artist without reloading. Without JavaScript the
  // form posts normally.
  function renderFollow(button, following) {
    const name = button.dataset.name;
    button.classList.toggle('following', following);
    button.setAttribute('aria-pressed', String(following));
    button.setAttribute('aria-label', `${following ? 'Unfollow' : 'Follow'} ${name}`);
    button.textContent = following ? 'Following' : 'Follow';
  }

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('.follow-form');
    if (!form) return;
    event.preventDefault();

    const button = form.querySelector('.follow-btn');
    if (button.disabled) return;
    button.disabled = true;

    try {
      const response = await fetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'fetch', Accept: 'application/json' },
        credentials: 'same-origin',
      });

      if (response.status === 401) {
        window.location.href = (await response.json()).login_url;
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const { following, followers } = await response.json();
      const artistId = form.dataset.artistId;

      // Every Follow button for this artist on the page stays in sync
      document.querySelectorAll(`.follow-form[data-artist-id="${artistId}"] .follow-btn`)
        .forEach((btn) => renderFollow(btn, following));
      document.querySelectorAll(`[data-followers-for="${artistId}"]`)
        .forEach((counter) => { counter.textContent = followers; });
      likeStatus.textContent = `${following ? 'Now following' : 'Unfollowed'} ${button.dataset.name}.`;

      // Profile page: an unfollowed artist leaves the Following list
      const followingGrid = form.closest('.following-grid');
      if (followingGrid && !following) {
        form.closest('.following-card').remove();
        const counter = document.getElementById('following-count');
        if (counter) counter.textContent = Math.max(0, Number(counter.textContent) - 1);
        if (!followingGrid.querySelector('.following-card')) {
          followingGrid.hidden = true;
          document.querySelector('.following-empty')?.removeAttribute('hidden');
        }
      }
    } catch (error) {
      console.error('Follow failed, falling back to a normal form post:', error);
      form.submit();
    } finally {
      button.disabled = false;
    }
  });

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
      if (navLinksContainer && navLinksContainer.classList.contains('show')) {
        toggleMobileMenu();
      }
    });
  });

  // 3. Mobile Menu Toggle Logic
  function toggleMobileMenu() {
    navLinksContainer.classList.toggle('show');
    
    // Switch the hamburger icon to an "X" close icon dynamically
    const icon = mobileToggle.querySelector('i');
    const open = navLinksContainer.classList.contains('show');
    icon.className = open ? 'fa-solid fa-xmark' : 'fa-solid fa-bars';
    mobileToggle.setAttribute('aria-expanded', String(open));
    mobileToggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }

  if (mobileToggle && navLinksContainer) {
    mobileToggle.addEventListener('click', toggleMobileMenu);
  }

  // Home page category shelf: arrow buttons scroll by roughly one view
  const shelf = document.getElementById('categories-scroller');
  const shelfArrows = document.querySelectorAll('[data-shelf-scroll]');

  if (shelf && shelfArrows.length) {
    const updateArrows = () => {
      const max = shelf.scrollWidth - shelf.clientWidth - 2;
      shelfArrows.forEach((arrow) => {
        const direction = Number(arrow.dataset.shelfScroll);
        arrow.disabled = direction < 0 ? shelf.scrollLeft <= 2 : shelf.scrollLeft >= max;
      });
    };

    shelfArrows.forEach((arrow) => {
      arrow.addEventListener('click', () => {
        const step = Math.max(shelf.clientWidth * 0.8, 160);
        shelf.scrollBy({ left: step * Number(arrow.dataset.shelfScroll) });
      });
    });

    shelf.addEventListener('scroll', updateArrows, { passive: true });
    window.addEventListener('resize', updateArrows);
    updateArrows();
  }

  // Profile photos that fail to load show the person's initial instead
  document.querySelectorAll('img.account-avatar[data-initial]').forEach((img) => {
    const fallback = () => {
      const initial = document.createElement('span');
      initial.className = img.className;
      initial.textContent = img.dataset.initial;
      img.replaceWith(initial);
    };
    if (img.complete && img.naturalWidth === 0) fallback();
    else img.addEventListener('error', fallback, { once: true });
  });

  // Account menu: profile, dashboard and logout in one dropdown
  const accountToggle = document.getElementById('account-toggle');
  const accountDropdown = document.getElementById('account-dropdown');

  function setAccountMenu(open) {
    accountDropdown.hidden = !open;
    accountToggle.setAttribute('aria-expanded', String(open));
  }

  if (accountToggle && accountDropdown) {
    accountToggle.addEventListener('click', (event) => {
      event.stopPropagation();
      setAccountMenu(accountDropdown.hidden);
    });

    document.addEventListener('click', (event) => {
      if (!accountDropdown.hidden && !accountDropdown.contains(event.target)) {
        setAccountMenu(false);
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !accountDropdown.hidden) {
        setAccountMenu(false);
        accountToggle.focus();
      }
    });
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

//products
document.addEventListener('DOMContentLoaded', () => {
  
  // Handle [♥] Wishlist Button Toggles
  const wishlistButtons = document.querySelectorAll('.wishlist-toggle-btn');
  
  wishlistButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation(); // Avoid card click conflicts
      
      const icon = btn.querySelector('i');
      btn.classList.toggle('liked');
      
      if (btn.classList.contains('liked')) {
        icon.className = 'fa-solid fa-heart';
        console.log("Added item to data-wishlist layer.");
      } else {
        icon.className = 'fa-regular fa-heart';
        console.log("Removed item from data-wishlist layer.");
      }
    });
  });

  // Handle [Add to Cart] Button Dispatches
  const addToCartButtons = document.querySelectorAll('.primary-add-btn');
  
  addToCartButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      
      const card = btn.closest('.sticker-card');
      const productId = card.getAttribute('data-id');
      const productName = card.querySelector('.product-name').textContent;
      
      console.log(`Dispatched: ${productName} (ID: ${productId}) targeted to basket pipeline.`);
      
      // Fast temporary animation feedback trigger
      const originalContent = btn.innerHTML;
      btn.innerHTML = `<i class="fa-solid fa-circle-check"></i> Added`;
      btn.style.backgroundColor = '#ff4500';
      btn.style.color = '#fff';
      
      setTimeout(() => {
        btn.innerHTML = originalContent;
        btn.style.backgroundColor = '';
        btn.style.color = '';
      }, 1000);
    });
  });
});