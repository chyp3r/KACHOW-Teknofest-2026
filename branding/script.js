document.addEventListener('DOMContentLoaded', () => {
    // Animate the progress bar on load
    setTimeout(() => {
        const progressBar = document.querySelector('.progress-fill');
        if (progressBar) {
            progressBar.style.width = '85%';
        }
    }, 500);

    // Simple interaction for feature tags
    const tags = document.querySelectorAll('.feature-tag');
    tags.forEach(tag => {
        tag.addEventListener('click', () => {
            tag.style.transform = 'scale(0.95)';
            setTimeout(() => {
                tag.style.transform = 'translateY(-2px)';
            }, 150);
        });
    });

    // Subtle parallax effect on background shapes
    document.addEventListener('mousemove', (e) => {
        const shapes = document.querySelectorAll('.shape');
        const x = e.clientX / window.innerWidth;
        const y = e.clientY / window.innerHeight;

        shapes.forEach((shape, index) => {
            const speed = (index + 1) * 20;
            const xOffset = (x - 0.5) * speed;
            const yOffset = (y - 0.5) * speed;
            shape.style.transform = `translate(${xOffset}px, ${yOffset}px)`;
        });
    });
});
