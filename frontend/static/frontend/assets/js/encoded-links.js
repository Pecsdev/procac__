(() => {
  const links = document.querySelectorAll('a[href]');

  links.forEach((link) => {
    const destination = new URL(link.href, window.location.href);
    if (destination.origin !== window.location.origin || !destination.pathname.startsWith('/')) {
      return;
    }

    if (
      destination.pathname === window.location.pathname
      && destination.search === window.location.search
    ) {
      return;
    }

    const route = `${destination.pathname}${destination.search}${destination.hash}`;
    const bytes = new TextEncoder().encode(route);
    const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
    const token = window.btoa(binary)
      .replaceAll('+', '-')
      .replaceAll('/', '_')
      .replace(/=+$/, '');
    link.href = `/go/${token}/`;
  });
})();
