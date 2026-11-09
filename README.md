# ClipScribe

Prática de ditado em inglês com vídeos locais, segmentos curtos e sincronização de legendas.

## Preparar o ambiente

```bash
cd /home/luiz/Documents/Codex/2026-11-07/atue-como-um-engenheiro-de-software/clipscribe
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
sudo apt-get update && sudo apt-get install -y ffmpeg
```

No macOS, substitua a última linha por `brew install ffmpeg`.

## Criar um clipe a partir de um episódio

```bash
python3 scripts/prepare_clip.py \
  --input "/caminho/para/B99-S04E19.mkv" \
  --start 00:04:10 \
  --end 00:06:10 \
  --title "B99 S04E19 - Wine Club" \
  --model base.en \
  --max-words 7
```

O comando cria `clips/<titulo>.mp4`, `.vtt` e `.srt`, depois cadastra o item em `clips/manifest.json`.

## Importar um episódio inteiro em micro-capítulos

No modal **+ Novo Clipe**, escolha **📺 Fatiar episódio completo**, informe o título e, opcionalmente, cole o transcript oficial. O ClipScribe transcreve uma única vez, usa esse texto para corrigir pequenas divergências sem perder os timestamps acústicos e cria partes naturais de 90, 120 ou 180 segundos.

O mesmo pipeline está disponível no terminal:

```bash
python3 scripts/slice_episode.py \
  --input "/caminho/para/B99-S04E19.mkv" \
  --title "B99 S04E19 - Your Honor" \
  --target-seconds 120 \
  --transcript-file "/caminho/para/transcript-oficial.txt" \
  --model base.en
```

As partes são registradas em um grupo no `clips/manifest.json`. A Biblioteca passa a exibi-las juntas, e ao concluir a última frase aparece **Ir para Parte seguinte**.

## Abrir a aplicação e criar clipes pela interface

```bash
python3 server.py --port 8000
```

Abra http://localhost:8000. Este é o comando único recomendado: ele serve a interface, habilita busca instantânea por HTTP Range nos vídeos e ativa o botão **+ Novo Clipe**. O modal aceita um caminho local ou upload, recorta com FFmpeg, transcreve com Whisper e registra o resultado na Biblioteca de Clipes.

Tanto `server.py` quanto `scripts/prepare_clip.py` detectam e usam automaticamente `.venv/bin/python`; não é necessário executar `source .venv/bin/activate` antes de iniciar o servidor.

O progresso, palavras críticas e o vocabulário são mantidos neste navegador via `localStorage`.

## Atalhos e prática final

- `Tab` ou `Ctrl + Espaço`: repetir o trecho atual.
- `Alt + K` ou `Ctrl + P`: pausar/continuar o vídeo.
- `Alt + H`: revelar a palavra atual e repetir o trecho.
- `Ctrl + ←` / `Ctrl + →`: navegar pelas frases.
- `Alt + R`: iniciar/parar a gravação de Shadowing.

Após gravar, use **🔁 Comparar**: o ClipScribe toca o áudio original do trecho e, ao terminar, toca imediatamente sua própria gravação. O recurso usa `MediaRecorder`, portanto funciona localmente sem depender do reconhecimento de voz do navegador.

Se você estiver usando apenas `python3 -m http.server`, a prática continua disponível, mas o modal exibirá o comando necessário para ativar o criador de clipes.

## Publicar a versão para alunos no GitHub Pages

O mesmo código possui dois modos:

- Em `localhost`, abre o modo administrador completo, com FFmpeg, Whisper, uploads e edição.
- No GitHub Pages, abre automaticamente o modo público: somente biblioteca, ditado, vocabulário, revisão e Shadowing. O progresso de cada aluno permanece no `localStorage` do próprio navegador.

A pasta local `clips/` é privada, tem mais de 1 GB e está no `.gitignore`. Somente os arquivos promovidos para `public/clips/` entram no site. Liste os clipes disponíveis com:

```bash
python3 scripts/publish_clip.py --list
```

Para publicar um clipe específico:

```bash
python3 scripts/publish_clip.py --id ID_DO_CLIPE
```

Para publicar todas as partes de um episódio:

```bash
python3 scripts/publish_clip.py --group ID_DO_GRUPO
```

Os IDs estão em `clips/manifest.json`. O comando copia o MP4 e as legendas, atualiza `public/manifest.json` e impede arquivos maiores que 100 MB ou uma biblioteca pública acima de 950 MB.

Teste exatamente a versão pública antes de enviar:

```bash
python3 scripts/build_public.py
python3 -m http.server 4173 --directory dist
```

Abra http://localhost:4173. A versão gerada em `dist/` já estará sem botões administrativos.

### Primeiro deploy

1. Crie um repositório público vazio no GitHub.
2. Envie o conteúdo desta pasta `clipscribe` como a raiz do repositório.
3. No GitHub, abra **Settings → Pages → Build and deployment**.
4. Em **Source**, escolha **GitHub Actions**.
5. Faça push para a branch `main`.

O workflow `.github/workflows/pages.yml` gera e publica o site automaticamente. Depois, cada novo `publish_clip.py` seguido de commit e push atualiza a biblioteca dos alunos.

> Publique apenas vídeos que você tem autorização para distribuir. Repositórios e sites gratuitos do GitHub Pages são públicos.
# clipscribe
