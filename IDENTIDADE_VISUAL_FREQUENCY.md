# Identidade visual do Frequency

Frequency é a ferramenta de gestão de uma academia: o símbolo une uma barra de treino a uma linha de ritmo. A identidade usa verde profundo para confiança e verde-lima para energia e movimento.

## Arquivos de marca

- `backend/static/brand-lockup.svg`: logo horizontal para fundos claros.
- `backend/static/brand-lockup-light.svg`: logo horizontal para fundos escuros.
- `backend/static/brand-mark.svg`: símbolo quadrado usado como favicon e ícone reduzido.
- Os ícones da navegação estão em SVG dentro de `backend/static/index.html`; a ilustração da tela de entrada é feita em CSS.

## Cores principais

| Uso | Cor |
|---|---|
| Texto e fundo escuro | `#14221c` |
| Verde da interface | `#315d42` |
| Verde-lima do símbolo e seleção | `#c6ef62` |
| Fundo claro | `#f4f5f0` |
| Superfície | `#ffffff` |

## Aplicação

Use a versão escura do logo em fundo claro e a versão clara em fundo escuro. Preserve o espaço interno do símbolo, não estique o SVG e prefira o ícone quadrado em tamanhos pequenos. O front usa fontes de sistema, SVG e CSS local; não depende de imagens remotas, fontes baixadas ou biblioteca de ícones.

## Monitor de entrada

O monitor tem uma identidade de alto contraste própria para leitura a alguns metros: fundo escuro, logo do Frequency ou logo opcional da academia, nome abreviado e mensagem curta. Um círculo com relógio indica que está aguardando; círculo verde com confirmação mostra acesso liberado; círculo vermelho com X mostra recusa. Cor e ícone acompanham sempre o texto para que a decisão não dependa apenas da cor.

O sinal de entrada liberada usa dois tons ascendentes curtos. A recusa usa dois tons mais graves e longos. Os sons são gerados localmente no navegador, sem arquivo ou serviço externo, e só ficam ativos depois do primeiro toque no próprio monitor. A mensagem e o estado desaparecem automaticamente para evitar que o próximo visitante veja o resultado anterior.
