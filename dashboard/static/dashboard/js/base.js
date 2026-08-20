document.addEventListener('DOMContentLoaded', () => {
    const clock = document.getElementById('clock');
    if (clock) {
        const tick = () => {
            const d = new Date();
            clock.textContent = d.toLocaleTimeString();
        };
        tick();
        setInterval(tick, 1000);
    }
});