# Package.json Guide

## Scripts
- dev: starts development server at localhost:5173
- build: compiles for production deployment
- lint: checks code quality
- preview: preview production build

## Dependencies (app needs these to run)
- react: UI framework
- react-dom: renders React in browser
- react-router-dom: page navigation (/database, /chat)
- tailwindcss: CSS styling
- lucide-react: icons
- three: 3D crystal viewer
- framer-motion: smooth animations
- sonner: toast notifications
- clsx + tailwind-merge: CSS class utilities

## DevDependencies (only for development)
- vite: build tool and dev server
- typescript: type checking
- @types/*: TypeScript type definitions
- oxlint: code quality checker