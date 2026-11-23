function openModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.add('open');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.remove('open');
        document.body.style.overflow = '';
    }
}

function switchModal(fromId, toId) {
    closeModal(fromId);
    openModal(toId);
}

function toggleMobileMenu() {
    const nav = document.getElementById('mainNav');
    nav.classList.toggle('show');
}

// Modal dışına tıklanınca kapatma
window.addEventListener('click', function(e) {
    if (e.target.classList.contains('modal-backdrop')) {
        e.target.classList.remove('open');
        document.body.style.overflow = '';
    }
});

// URL parametresi ile otomatik modal açma (?modal=b2b-login vb.)
window.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    const modal = params.get('modal');
    if (modal === 'b2b-login') openModal('b2bLoginModal');
    if (modal === 'plasiyer-login') openModal('plasiyerLoginModal');
    if (modal === 'b2b-register') openModal('b2bRegisterModal');
});
