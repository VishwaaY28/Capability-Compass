import typography from '@tailwindcss/typography'
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#3C2DDA',
      },
      typography: {
        DEFAULT: {
          css: {
            h1: {
              fontWeight: '600',
              marginTop: '1.5em',
              marginBottom: '0.5em',
            },
            h2: {
              fontWeight: '600',
              marginTop: '1.25em',
              marginBottom: '0.5em',
            },
            h3: {
              fontWeight: '600',
              marginTop: '1em',
              marginBottom: '0.5em',
            },
            'ul > li': {
              paddingLeft: '0.5em',
            },
            'ol > li': {
              paddingLeft: '0.5em',
            },
            code: {
              fontWeight: '400',
              backgroundColor: 'rgb(243 244 246)',
              padding: '0.2em 0.4em',
              borderRadius: '0.25em',
            },
            pre: {
              backgroundColor: 'rgb(31 41 55)',
              color: 'rgb(229 231 235)',
              fontWeight: '400',
              padding: '1em',
              borderRadius: '0.5em',
              marginTop: '1em',
              marginBottom: '1em',
            },
            blockquote: {
              fontWeight: '400',
              fontStyle: 'italic',
              borderLeftWidth: '4px',
              borderLeftColor: 'rgb(209 213 219)',
              paddingLeft: '1em',
            },
          },
        },
      },
    },
  },
  plugins: [typography],
}
