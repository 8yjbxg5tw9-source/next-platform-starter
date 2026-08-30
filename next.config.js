/** @type {import('next').NextConfig} */
const nextConfig = {
  // React Compiler burada söndürülüb.
  // Səbəb: "babel-plugin-react-compiler" package.json-de birbaşa yazılmayıb,
  // yalnız package-lock-da tranzitiv asılılıq kimi var. Təmiz "npm install"
  // (npm ci-dən fərqli) onu Next-in gözlədiyi yerdə qurmaya bilir və
  // "Failed to resolve package babel-plugin-react-compiler" xətası verir.
  // Compiler yalnız opsional build optimallaşdırmasıdır; söndürmək funksiyanı
  // dəyişdirmir və xətanı hər mühitdə aradan qaldırır.
  reactCompiler: false,

  // Arena canlı önizlemesi sayfayı https://{port}-{sandbox}.e2b.app üzerinden
  // proxy'ler. Dev modunda cross-origin uyarısını/kısıtını önlemek için izin ver.
  allowedDevOrigins: ['3000-ib4i2jk694mlwwl243mxo.e2b.app', '*.e2b.app'],

  redirects() {
    return [
      {
        source: '/docs',
        destination: 'https://docs.netlify.com/frameworks/next-js/overview/',
        permanent: false,
      },
      {
        source: '/old-blog/:slug',
        destination: '/classics',
        permanent: true,
      },
      {
        source: '/github',
        destination: 'https://github.com/netlify-templates/next-platform-starter',
        permanent: false,
      },
      {
        source: '/home',
        destination: '/',
        permanent: true,
      },
    ];
  },
  
  rewrites() {
    return [
      {
        source: '/api/health',
        destination: '/quotes/random',
      },
      {
        source: '/blog',
        destination: '/classics',
      },
    ];
  },
};

export default nextConfig;
