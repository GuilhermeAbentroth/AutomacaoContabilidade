import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, filedialog
import threading


class EmissorBethaModulo:
    def __init__(self, parent):
        self.parent = parent
        self.container = parent.container

    # =========================================================================
    # UI COM CUSTOM TKINTER
    # =========================================================================
    def tela_emissor_betha(self):
        self.parent.limpar_tela()

        # Logo no topo
        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.parent.carregar_logo(f_l)

        # Título da tela
        ctk.CTkLabel(self.container, text="Emissor NFSE - Betha (Em Lote)", font=("Arial", 22, "bold"),
                     text_color="#8e44ad").pack(pady=(0, 10))

        # Card de Formulários
        f_card = ctk.CTkFrame(self.container)
        f_card.pack(fill="x", padx=40, pady=10)

        # --- LINHA 1: SELEÇÃO DA PLANILHA EXCEL ---
        f_excel = ctk.CTkFrame(f_card, fg_color="transparent")
        f_excel.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(f_excel, text="Planilha Base:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(
            side=tk.LEFT)

        self.ent_excel_nfse = ctk.CTkEntry(f_excel, font=("Arial", 12), width=450)
        self.ent_excel_nfse.pack(side=tk.LEFT, padx=10)

        def selecionar_planilha():
            p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
            if p:
                self.ent_excel_nfse.delete(0, tk.END)
                self.ent_excel_nfse.insert(0, p)

        ctk.CTkButton(f_excel, text="Procurar", command=selecionar_planilha, width=100).pack(side=tk.LEFT, padx=5)

        # --- LINHA 2: CREDENCIAIS DE LOGIN ---
        f_login = ctk.CTkFrame(f_card, fg_color="transparent")
        f_login.pack(fill="x", padx=20, pady=(10, 20))

        ctk.CTkLabel(f_login, text="Usuário:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(side=tk.LEFT)
        self.ent_usuario = ctk.CTkEntry(f_login, font=("Arial", 12), width=180)
        self.ent_usuario.pack(side=tk.LEFT, padx=10)

        ctk.CTkLabel(f_login, text="Senha:", font=("Arial", 12, "bold"), width=60, anchor="e").pack(side=tk.LEFT,
                                                                                                    padx=(20, 10))
        self.ent_senha = ctk.CTkEntry(f_login, font=("Arial", 12), width=180, show="*")  # show="*" oculta a senha
        self.ent_senha.pack(side=tk.LEFT, padx=10)

        # --- CAIXA DE LOGS ---
        f_log_area = ctk.CTkFrame(self.container, fg_color="transparent")
        f_log_area.pack(fill="both", expand=True, padx=40, pady=5)

        # Mantendo o ScrolledText mas com cores que combinam com o CustomTkinter
        self.parent.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=12, state='disabled',
                                                        bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(fill="both", expand=True)

        # --- BOTÕES DE AÇÃO ---
        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)

        ctk.CTkButton(f_btns, text="▶ ACESSAR SISTEMA E EMITIR", command=self.start_thread,
                      fg_color="#8e44ad", hover_color="#732d91", font=("Arial", 14, "bold"), height=50, width=350).pack(
            side="left", padx=20)

        ctk.CTkButton(f_btns, text="Voltar Menu", command=self.parent.mostrar_menu_inicial,
                      fg_color="gray", hover_color="darkgray", font=("Arial", 14), height=50, width=150).pack(
            side="left")

    def start_thread(self):
        threading.Thread(target=self.executar_automacao, daemon=True).start()

    # =========================================================================
    # LÓGICA DE AUTOMAÇÃO (MANTIDA INTACTA)
    # =========================================================================
    def executar_automacao(self):
        import pandas as pd
        from playwright.sync_api import sync_playwright
        import time
        from datetime import datetime
        import socket
        import subprocess
        import os

        # Pegando os valores da tela
        caminho_excel = self.ent_excel_nfse.get().strip()
        usuario_betha = self.ent_usuario.get().strip()
        senha_betha = self.ent_senha.get().strip()

        # Validação inicial
        if not caminho_excel or not os.path.exists(caminho_excel):
            self.parent.log_msg("ERRO: Selecione uma planilha Excel válida primeiro!", "erro")
            return

        if not usuario_betha or not senha_betha:
            self.parent.log_msg("ERRO: Informe o Usuário e a Senha antes de continuar!", "erro")
            return

        def verificar_porta_debug():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(('127.0.0.1', 9222)) == 0

        debug_profile = r"C:\ChromeDebug_Betha"

        try:
            self.parent.log_msg("Lendo planilha Excel...")
            df_notas = pd.read_excel(caminho_excel)
            total_notas = len(df_notas)
            self.parent.log_msg(f"Encontradas {total_notas} notas para emitir na planilha.")

            chrome_path = self.parent.configuracoes.get("chrome_path", "")
            if not chrome_path or not os.path.exists(chrome_path):
                self.parent.log_msg("ERRO: Configure o caminho do Chrome na engrenagem.", "erro")
                return

            if not os.path.exists(debug_profile):
                os.makedirs(debug_profile)

            if not verificar_porta_debug():
                self.parent.log_msg("Iniciando navegador Chrome independente...")
                comando = [
                    chrome_path, "--remote-debugging-port=9222",
                    f"--user-data-dir={debug_profile}", "--no-first-run",
                    "--start-maximized", "--no-default-browser-check",
                    "--disable-session-crashed-bubble", "--disable-infobars"
                ]
                subprocess.Popen(comando)
                time.sleep(4)
            else:
                self.parent.log_msg("Conectando ao navegador Chrome já aberto...")
                time.sleep(2)

            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]

                page = context.new_page()
                page.bring_to_front()

                time.sleep(2)
                url = "https://nota-eletronica.betha.cloud/#/inicio"
                self.parent.log_msg("Acessando portal Betha (Tela Inicial)...")

                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except:
                    pass

                time.sleep(4)

                page.mouse.click(500, 300)
                time.sleep(1)

                self.parent.log_msg("Executando TAB TAB ENTER para abrir a tela de Login...")
                with context.expect_page() as nova_aba_info:
                    page.keyboard.press("Tab")
                    time.sleep(0.5)
                    page.keyboard.press("Tab")
                    time.sleep(0.5)
                    page.keyboard.press("Enter")

                nova_aba = nova_aba_info.value

                self.parent.log_msg("Aguardando carregamento da nova guia de login...")
                nova_aba.wait_for_load_state("networkidle")
                time.sleep(2)

                self.parent.log_msg("Efetuando Login com credenciais da tela...")
                # Substituição das credenciais fixas pelas variáveis da tela
                nova_aba.keyboard.type(usuario_betha)
                time.sleep(0.5)
                nova_aba.keyboard.press("Tab")
                time.sleep(0.5)
                nova_aba.keyboard.type(senha_betha)
                time.sleep(0.5)
                nova_aba.keyboard.press("Enter")

                nova_aba.wait_for_load_state("networkidle")
                time.sleep(3)

                self.parent.log_msg("Rolando a tela para carregar a lista de empresas...")
                nova_aba.keyboard.press("PageDown")
                time.sleep(0.5)
                nova_aba.keyboard.press("PageDown")
                time.sleep(0.5)

                self.parent.log_msg("Procurando e clicando na empresa PRÁTICA CONTABILIDADE LTDA...")
                try:
                    empresa = nova_aba.locator("text=/PR[ÁA]TICA CONTABILIDADE LTDA/i").first
                    empresa.wait_for(state="attached", timeout=4000)
                    empresa.click(force=True)
                except:
                    nova_aba.evaluate("""
                        const elementos = document.querySelectorAll('*');
                        for (let el of elementos) {
                            if (el.innerText && el.innerText.toUpperCase().includes('PRÁTICA CONTABILIDADE LTDA')) {
                                el.click();
                                break;
                            }
                        }
                    """)

                nova_aba.wait_for_load_state("networkidle")
                time.sleep(4)

                self.parent.log_msg("Verificando se há modal de aviso na tela...")
                try:
                    aviso = nova_aba.locator("text=/Não mostrar novamente/i").first
                    aviso.wait_for(state="visible", timeout=3000)
                    aviso.click(force=True)
                    time.sleep(1)

                    btn_fechar = nova_aba.locator(
                        "button:has-text('Fechar'), button:has-text('Entendi'), button:has-text('OK')").first
                    if btn_fechar.is_visible():
                        btn_fechar.click(force=True)
                        time.sleep(1)
                except:
                    pass

                self.parent.log_msg("Acessando o 3º ícone (Notas Fiscais) na barra lateral...")
                try:
                    icone_nota = nova_aba.locator("[title*='Notas fiscais' i], [title*='Nota fiscal' i]").first
                    icone_nota.wait_for(state="attached", timeout=3000)
                    icone_nota.click(force=True)
                except:
                    nova_aba.evaluate("""
                        const sidebars = document.querySelectorAll('aside, nav, .menu, .sidebar, ul[class*="menu"]');
                        for (let nav of sidebars) {
                            const items = nav.querySelectorAll('a, button, li');
                            if (items.length >= 3) {
                                items[2].click();
                                break;
                            }
                        }
                    """)

                nova_aba.wait_for_load_state("networkidle")
                time.sleep(2)

                self.parent.log_msg("Recolhendo o menu lateral...")
                nova_aba.keyboard.press("Escape")
                time.sleep(0.5)

                self.parent.log_msg("Clicando no botão '+ DPS'...")
                try:
                    btn_dps = nova_aba.locator("text=+ DPS").first
                    btn_dps.wait_for(state="visible", timeout=3000)
                    btn_dps.click(force=True)
                except:
                    btn_dps = nova_aba.locator("button:has-text('DPS')").first
                    btn_dps.click(force=True)

                nova_aba.wait_for_load_state("networkidle")
                time.sleep(3)

                data_atual = datetime.now().strftime("%d/%m/%Y")
                self.parent.log_msg(f"Localizando o campo e preenchendo a Data de Prestação: {data_atual}")

                try:
                    campo_data = nova_aba.locator(
                        "xpath=//*[contains(text(), 'Data Prestação do Serviço')]/following::input[1] >> visible=true").first
                    campo_data.wait_for(state="visible", timeout=5000)
                    campo_data.click(force=True)
                    nova_aba.keyboard.type(data_atual)
                except:
                    nova_aba.locator("text=Data Prestação do Serviço >> visible=true").first.click(force=True)
                    nova_aba.keyboard.press("Tab")
                    nova_aba.keyboard.type(data_atual)

                self.parent.log_msg("Iniciando emissão em lote...", divisor=True)

                for index, row in df_notas.iterrows():
                    cnpj_raw = str(row.get('CNPJ', '')).strip()
                    cnpj_limpo = "".join(filter(str.isdigit, cnpj_raw))

                    valor_lido = row.get('VALOR', 0)
                    try:
                        if isinstance(valor_lido, str):
                            if ',' in valor_lido and '.' in valor_lido:
                                valor_lido = valor_lido.replace('.', '').replace(',', '.')
                            elif ',' in valor_lido:
                                valor_lido = valor_lido.replace(',', '.')

                        v_float = float(valor_lido)
                        valor_raw = f"{v_float:.2f}".replace('.', ',')
                    except:
                        valor_raw = str(valor_lido)

                    self.parent.log_msg(
                        f"Processando Nota {index + 1}/{total_notas} - CNPJ: {cnpj_limpo} | R$ {valor_raw}")

                    time.sleep(1)

                    for _ in range(3):
                        nova_aba.keyboard.press("Tab")
                        time.sleep(0.05)

                    nova_aba.keyboard.press("Space")
                    time.sleep(0.5)

                    for _ in range(2):
                        nova_aba.keyboard.press("Tab")
                        time.sleep(0.05)

                    self.parent.log_msg("Digitando o CNPJ pausadamente...")
                    cnpj_parcial = cnpj_limpo[:-1] if len(cnpj_limpo) > 1 else cnpj_limpo
                    nova_aba.keyboard.type(cnpj_parcial, delay=200)
                    time.sleep(1.5)

                    nova_aba.keyboard.press("ArrowDown")
                    time.sleep(0.5)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(2)

                    self.parent.log_msg("Clicando no botão Avançar...")
                    try:
                        btn_avancar = nova_aba.locator("button:has-text('Avançar') >> visible=true").first
                        btn_avancar.wait_for(state="visible", timeout=5000)
                        btn_avancar.click(force=True)
                    except:
                        nova_aba.locator("text=Avançar >> visible=true").first.click(force=True)

                    nova_aba.wait_for_load_state("networkidle")
                    time.sleep(3)

                    self.parent.log_msg("Procurando o campo País da prestação...")
                    try:
                        campo_pais = nova_aba.locator(
                            "xpath=//*[contains(text(), 'País da prestação')]/following::input[1] >> visible=true").first
                        campo_pais.wait_for(state="visible", timeout=5000)
                        campo_pais.click(force=True)
                    except:
                        nova_aba.locator("text=País da prestação >> visible=true").first.click(force=True)
                        nova_aba.keyboard.press("Tab")

                    time.sleep(1)

                    nova_aba.keyboard.type("BRA", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("JARAGUA DO SUL", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("O", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("N", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("1719", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("1130", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("Serviços de Contabilidade", delay=100)
                    time.sleep(0.3)

                    self.parent.log_msg("Clicando no botão Avançar...")
                    try:
                        btn_avancar2 = nova_aba.locator("button:has-text('Avançar') >> visible=true").first
                        btn_avancar2.wait_for(state="visible", timeout=5000)
                        btn_avancar2.click(force=True)
                    except:
                        nova_aba.locator("text=Avançar >> visible=true").first.click(force=True)

                    nova_aba.wait_for_load_state("networkidle")
                    time.sleep(3)

                    self.parent.log_msg("Procurando o campo Valor total do serviço...")
                    try:
                        campo_valor = nova_aba.locator(
                            "xpath=//*[contains(text(), 'Valor total do serviço')]/following::input[1] >> visible=true").first
                        campo_valor.wait_for(state="visible", timeout=5000)
                        campo_valor.click(force=True)
                    except:
                        nova_aba.locator("text=Valor total do serviço >> visible=true").first.click(force=True)
                        nova_aba.keyboard.press("Tab")

                    nova_aba.wait_for_load_state("networkidle")
                    time.sleep(2)

                    self.parent.log_msg("Digitando o valor da planilha...")
                    nova_aba.keyboard.type(valor_raw, delay=150)
                    time.sleep(0.5)

                    for _ in range(3):
                        nova_aba.keyboard.press("Tab")
                        time.sleep(0.1)

                    nova_aba.keyboard.type("N", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("N", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.press("Space")
                    time.sleep(0.2)

                    nova_aba.keyboard.press("Tab")
                    time.sleep(0.1)

                    nova_aba.keyboard.type("N", delay=100)
                    time.sleep(0.3)
                    nova_aba.keyboard.press("Enter")
                    time.sleep(0.3)

                    self.parent.log_msg("Clicando no botão Avançar...")
                    try:
                        btn_avancar3 = nova_aba.locator("button:has-text('Avançar') >> visible=true").first
                        btn_avancar3.wait_for(state="visible", timeout=5000)
                        btn_avancar3.click(force=True)
                    except:
                        nova_aba.locator("text=Avançar >> visible=true").first.click(force=True)

                    time.sleep(2)

                    self.parent.log_msg("Clicando no botão EMITIR DPS...")
                    try:
                        btn_emitir = nova_aba.locator("button:has-text('EMITIR DPS') >> visible=true").first
                        btn_emitir.wait_for(state="visible", timeout=5000)
                        btn_emitir.click(force=True)
                    except:
                        nova_aba.locator("text=EMITIR DPS >> visible=true").first.click(force=True)

                    self.parent.log_msg("Aguardando processamento da emissão...")
                    time.sleep(7)
                    self.parent.estatisticas.registrar_evento("nota_emitida")

                    self.parent.log_msg("Limpando possíveis modais de sucesso...")
                    nova_aba.keyboard.press("Escape")
                    time.sleep(1)

                    self.parent.log_msg("Resetando a tela via manipulação de URL...")
                    url_atual = nova_aba.url

                    if "/notas-fiscais" in url_atual:
                        base_url = url_atual.split("/notas-fiscais")[0]
                    else:
                        base_url = url_atual.rsplit("/", 1)[0]

                    url_visao_geral = base_url + "/visao-geral"
                    url_notas_fiscais = base_url + "/notas-fiscais/listagem"

                    try:
                        nova_aba.goto(url_visao_geral)
                        nova_aba.wait_for_load_state("networkidle")
                    except:
                        pass
                    time.sleep(3)

                    if index < total_notas - 1:
                        self.parent.log_msg("Preparando a próxima nota: Retornando para Notas Fiscais via URL...")
                        try:
                            nova_aba.goto(url_notas_fiscais)
                            nova_aba.wait_for_load_state("networkidle")
                        except:
                            pass
                        time.sleep(3)

                        try:
                            btn_dps = nova_aba.locator("text=+ DPS >> visible=true").first
                            btn_dps.wait_for(state="visible", timeout=5000)
                            btn_dps.click(force=True)
                        except:
                            btn_dps = nova_aba.locator("button:has-text('DPS') >> visible=true").first
                            btn_dps.click(force=True)

                        nova_aba.wait_for_load_state("networkidle")
                        time.sleep(3)

                        self.parent.log_msg("Refazendo o foco na Data de Prestação...")
                        try:
                            campo_data = nova_aba.locator(
                                "xpath=//*[contains(text(), 'Data Prestação do Serviço')]/following::input[1] >> visible=true").first
                            campo_data.wait_for(state="visible", timeout=5000)
                            campo_data.click(force=True)
                            nova_aba.keyboard.type(data_atual)
                        except:
                            nova_aba.locator("text=Data Prestação do Serviço >> visible=true").first.click(
                                force=True)
                            nova_aba.keyboard.press("Tab")
                            nova_aba.keyboard.type(data_atual)

            self.parent.log_msg("Todas as notas foram processadas!", "sucesso")

        except Exception as e:
            self.parent.log_msg(f"Erro na automação: {e}", "erro")