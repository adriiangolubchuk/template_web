document.addEventListener('DOMContentLoaded', () => {
    const drawerToggle = document.getElementById('sidebar-drawer');
    const drawerContent = document.querySelector('.drawer-content');

    // Закрываем drawer при клике на пункт меню на мобильных устройствах
    document.querySelectorAll('.drawer-side .menu a').forEach(link => {
        link.addEventListener('click', () => {
            if (window.innerWidth < 1024) {
                drawerToggle.checked = false;
            }
        });
    });

    // Закрываем drawer при клике на контент на мобильных устройствах
    drawerContent.addEventListener('click', () => {
        if (window.innerWidth < 1024 && drawerToggle.checked) {
            drawerToggle.checked = false;
        }
    });
});