document.addEventListener('DOMContentLoaded', () => {
  const navItems = document.querySelectorAll('.nav-item');
  const actionItems = document.querySelectorAll('.action-item');

  // Handle Dynamic Active States for Nav links
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      // Don't interrupt dropdown toggle triggers if needed later
      if(item.classList.contains('dropdown')) return;

      navItems.forEach(nav => nav.classList.remove('active'));
      item.classList.add('active');
    });
  });

  // Example Event Listeners for interactive elements
  actionItems.forEach(action => {
    action.addEventListener('click', () => {
      const label = action.querySelector('.action-label').textContent;
      console.log(`${label} clicked!`);
      // Add your modal triggers or navigation redirect routing logic here
    });
  });
});