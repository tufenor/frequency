# TypeScript e performance do frontend Frequency

## O que entrou na V1

- `src/site.ts` é compilado em modo estrito para `public/static/generated/site.js`.
- `tsconfig.json` usa `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `useUnknownInCatchVariables` e `forceConsistentCasingInFileNames`.
- O script `npm run typecheck` valida os tipos sem gerar arquivos; `npm run build` compila o TypeScript antes de montar `dist`.
- O controlador público tem tipos para idioma, país, planos, preços, cotação e serviço de tradução. O painel autenticado continua servido pelo `app.js` existente para preservar os fluxos já validados.

## Performance e busca

- A cotação externa é carregada em idle time e nunca bloqueia a primeira pintura; há fallback local para operação sem rede.
- A página pública ganhou `robots`, `theme-color`, Open Graph/Twitter, descrição em português, link de salto para teclado, landmarks e dimensões explícitas da marca.
- CSS responsivo cobre desktop, tablet, telas pequenas, foco visível e `prefers-reduced-motion`; seções abaixo da dobra usam renderização adiada do navegador.
- O service worker inclui a entrada pública e os assets versionados, sem armazenar dados privados de usuários.

## Próximo limite seguro

A migração integral do painel para React/TypeScript deve ser feita por módulos, guiada por `API_CONTRACT.md` e com testes de cada fluxo. Substituir o painel inteiro agora aumentaria o risco sem ganho comprovado de SEO: o Google indexa a entrada pública, enquanto a área autenticada deve priorizar estabilidade e segurança.
