# =========================================================================
# Versão única do aplicativo — fonte da verdade para main.py (título/Sobre)
# e atualizador_modulo.py (comparação de versão).
#
# NÃO precisa mais editar este valor manualmente antes de cada release: o
# workflow de build (.github/workflows/build-release.yml) sobrescreve esta
# linha automaticamente com o número da tag do git no momento do build
# (ex.: tag "v10.6" -> VERSAO = "10.6"). Editar aqui só importa para rodar
# a partir do código-fonte (sem build), fora do fluxo normal de release.
# =========================================================================
VERSAO = "10.5"
