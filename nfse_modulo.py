import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import os
import time
import socket
import subprocess
import calendar
from datetime import datetime, date
import shutil
import re
import pandas as pd
from pypdf import PdfReader


class PortalNacionalModulo:
    def __init__(self, parent):
        self.parent = parent
        self.container = parent.container
        self.pasta_exe = parent.pasta_exe
        self.debug_profile = r"C:\ChromeDebug_NFSe"
        self.parar_solicitado = False

    def selecionar_pasta(self):
        p = filedialog.askdirectory()
        if p:
            self.ent_caminho.delete(0, tk.END)
            self.ent_caminho.insert(0, p)

    def verificar_porta_debug(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', 9222)) == 0

    def interromper_processo(self):
        self.parar_solicitado = True
        self.parent.log_msg("Parada solicitada! Finalizando nota atual...", "erro")

    def converter_valor_br(self, texto):
        try:
            limpo = texto.replace(".", "").replace(",", ".")
            return float(limpo)
        except:
            return 0.0

    def extrair_dados_entidade(self, texto_bloco):
        """ Extrai Razão Social e CNPJ, limpando e-mails """
        doc = "Não identificado"
        match_cnpj = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', texto_bloco)
        if match_cnpj:
            doc = match_cnpj.group(0)
        else:
            match_cpf = re.search(r'\d{3}\.\d{3}\.\d{3}-\d{2}', texto_bloco)
            if match_cpf: doc = match_cpf.group(0)

        nome = "Não identificado"
        match_nome = re.search(r"Nome / Nome Empresarial\s+(.+?)\s+(?:Endereço|CNPJ|CPF|Inscrição|E-mail)", texto_bloco,
                               re.IGNORECASE | re.DOTALL)

        if match_nome:
            raw_name = match_nome.group(1)
            raw_name = re.sub(r'\S+@\S+', '', raw_name)
            nome = raw_name.replace("\n", " ").replace("  ", " ").strip()
            if len(nome) < 3:
                linhas = raw_name.split('\n')
                if linhas: nome = linhas[0].strip()

        return f"{nome} - {doc}"

    def abrir_portal_nacional(self, log_func):
        chrome_path = self.parent.configuracoes.get("chrome_path")
        if not chrome_path or not os.path.exists(chrome_path):
            messagebox.showwarning("Atenção", "Configure o caminho do Chrome na engrenagem (⚙).")
            return
        if not os.path.exists(self.debug_profile): os.makedirs(self.debug_profile)
        if not self.verificar_porta_debug():
            comando = [
                chrome_path, "--remote-debugging-port=9222",
                f"--user-data-dir={self.debug_profile}", "--no-first-run",
                "--ignore-certificate-errors"
            ]
            subprocess.Popen(comando)
            log_func("Abrindo Chrome em modo Depuração...")
            time.sleep(4)
        log_func("Acesse o portal e aguarde o Dashboard para iniciar.")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                pagina = context.pages[0] if context.pages else context.new_page()
                pagina.goto("https://www.nfse.gov.br/EmissorNacional/Login")
        except:
            pass

    def iniciar_automacao_geral(self, log_func, tipo):
        self.parar_solicitado = False
        vel_config = self.parent.configuracoes.get("velocidade", "1")
        mult = 1.0 if vel_config == "1" else (0.5 if vel_config == "2" else 0.05)

        arquivos_para_processar = []

        try:
            from playwright.sync_api import sync_playwright
        except:
            messagebox.showerror("Erro", "Playwright não instalado.")
            return

        if not self.verificar_porta_debug():
            messagebox.showwarning("Erro", "Chrome não detectado. Use o Botão 1.")
            return

        strCaminhoBase = self.ent_caminho.get()
        strDtaIni = self.ent_data_ini.get()
        strDtaFim = self.ent_data_fim.get()
        self.parent.salvar_config("ultimo_caminho", strCaminhoBase)

        if tipo == 1:
            url_alvo = "https://www.nfse.gov.br/EmissorNacional/Notas/Recebidas"
            nome_pasta_mae = "NFSE DESTINADA"
        else:
            url_alvo = "https://www.nfse.gov.br/EmissorNacional/Notas/Emitidas"
            nome_pasta_mae = "NFSE EMITIDA"

        pasta_raiz = os.path.abspath(os.path.join(strCaminhoBase, nome_pasta_mae))
        os.makedirs(pasta_raiz, exist_ok=True)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                pagina = next((p for p in context.pages if "nfse.gov.br" in p.url), None)
                if not pagina:
                    log_func("Portal não detectado.", "erro")
                    return

                pagina.goto(url_alvo)
                pagina.wait_for_selector("#datainicio", state="visible", timeout=60000)
                time.sleep(2 * mult)

                def obter_intervalos(d1, d2):
                    dt_ini = datetime.strptime(d1, "%d/%m/%Y").date()
                    dt_fim = datetime.strptime(d2, "%d/%m/%Y").date()
                    intervalos = []
                    ano, mes = dt_ini.year, dt_ini.month
                    while True:
                        u_dia = calendar.monthrange(ano, mes)[1]
                        fim_int = min(date(ano, mes, u_dia), dt_fim)
                        ini_int = max(date(ano, mes, 1), dt_ini)
                        intervalos.append((ini_int.strftime("%d/%m/%Y"), fim_int.strftime("%d/%m/%Y")))
                        if ano == dt_fim.year and mes == dt_fim.month: break
                        mes += 1
                        if mes > 12: mes = 1; ano += 1
                    return intervalos

                for inicio, fim in obter_intervalos(strDtaIni, strDtaFim):
                    if self.parar_solicitado: break
                    log_func(f"Filtrando: {inicio} a {fim}", divisor=True)
                    pagina.evaluate(f"document.getElementById('datainicio').value = '{inicio}'")
                    pagina.evaluate(f"document.getElementById('datafim').value = '{fim}'")
                    pagina.evaluate("document.getElementById('datainicio').dispatchEvent(new Event('change'))")
                    pagina.evaluate("document.getElementById('datafim').dispatchEvent(new Event('change'))")
                    time.sleep(1 * mult)
                    pagina.get_by_role("button", name="Filtrar").click()

                    log_func("Aguardando tabela...")
                    try:
                        pagina.wait_for_selector("tbody tr, .alert-warning", timeout=60000)
                    except:
                        pagina.get_by_role("button", name="Filtrar").click()
                        pagina.wait_for_selector("tbody tr", timeout=30000)

                    pagina.wait_for_load_state("load")
                    time.sleep(2 * mult)

                    if pagina.get_by_text('Total de ').count() > 0:
                        total_texto = pagina.get_by_text('Total de ').inner_text()
                        match = re.search(r'(\d+)', total_texto.split(' de ')[-1])
                        total_notas = int(match.group(1)) if match else int(total_texto.split(' ')[2])
                        baixados = 0
                        log_func(f"Total: {total_notas} notas.")

                        while baixados < total_notas:
                            if self.parar_solicitado: break
                            pagina.wait_for_selector("tbody tr", state="visible", timeout=30000)
                            time.sleep(1.5 * mult)
                            linhas = pagina.locator("tbody tr")
                            if linhas.count() == 0: time.sleep(2); linhas = pagina.locator("tbody tr")

                            for i in range(linhas.count()):
                                if baixados >= total_notas or self.parar_solicitado: break
                                try:
                                    linha = linhas.nth(i)
                                    linha.scroll_into_view_if_needed()
                                    status_raw = linha.locator(".td-situacao > img").get_attribute(
                                        'data-original-title') or "Outros"
                                    status_limpo = status_raw.replace("NFS-e ", "").replace("à outra NFS-e", "").strip()

                                    if tipo == 1:
                                        t_xml, t_pdf = 2, 3
                                    else:
                                        t_xml, t_pdf = (2,
                                                        3) if "substituição" in status_raw.lower() or "cancelada" in status_raw.lower() else (
                                            4, 5)

                                    log_func(f"Baixando Nota {baixados + 1}...")
                                    botao_acao = linha.locator("td").last.locator("a, button").first
                                    botao_acao.wait_for(state="attached", timeout=10000)
                                    try:
                                        botao_acao.click(force=True, timeout=5000)
                                    except:
                                        pagina.evaluate("(el) => el.click()", botao_acao.element_handle())
                                    time.sleep(1.5 * mult)

                                    with pagina.expect_download(timeout=60000) as d_xml:
                                        for _ in range(t_xml): pagina.keyboard.press("Tab")
                                        pagina.keyboard.press("Enter")
                                    f_xml = d_xml.value
                                    nome_xml = f_xml.suggested_filename
                                    if not nome_xml.endswith(".xml"): nome_xml += ".xml"
                                    f_xml.save_as(os.path.join(pasta_raiz, nome_xml))
                                    pagina.keyboard.press("Escape")
                                    time.sleep(1.2 * mult)

                                    try:
                                        pagina.evaluate("(el) => el.click()", botao_acao.element_handle())
                                    except:
                                        botao_acao.click(force=True)
                                    time.sleep(1.5 * mult)
                                    try:
                                        with pagina.expect_download(timeout=30000) as d_pdf:
                                            for _ in range(t_pdf): pagina.keyboard.press("Tab")
                                            pagina.keyboard.press("Enter")
                                        d_pdf.value.save_as(os.path.join(pasta_raiz, nome_xml.replace(".xml", ".pdf")))
                                    except:
                                        pass

                                    pagina.keyboard.press("Escape")
                                    time.sleep(1 * mult)

                                    arquivos_para_processar.append({
                                        'nome_base': nome_xml.replace(".xml", ""),
                                        'subpasta_destino': status_limpo
                                    })
                                    baixados += 1
                                    log_func(f"Download {baixados}/{total_notas} OK")
                                except Exception as e:
                                    log_func(f"Erro: {str(e)[:20]}", "erro")
                                    pagina.keyboard.press("Escape")
                                    time.sleep(2 * mult)

                            if baixados < total_notas and not self.parar_solicitado:
                                seta = pagina.get_by_role("link", name="")
                                if seta.is_visible():
                                    log_func("Trocando página...")
                                    seta.click()
                                    pagina.wait_for_load_state("load")
                                    time.sleep(3 * mult)
                                else:
                                    break
                            else:
                                break

                # --- FASE 2: PROCESSAMENTO (PDF + EXCEL) ---
                if arquivos_para_processar and not self.parar_solicitado:
                    log_func("Gerando Excel Contábil...", "info", divisor=True)
                    dados_excel = []

                    for item in arquivos_para_processar:
                        nome_base = item['nome_base']
                        subpasta = item['subpasta_destino']
                        caminho_pdf = os.path.join(pasta_raiz, nome_base + ".pdf")
                        caminho_xml = os.path.join(pasta_raiz, nome_base + ".xml")

                        val_servico = 0.0
                        val_liquido = 0.0
                        data_emissao = ""
                        numero_nf = "Não identificado"
                        retencao = "NÃO"
                        prestador = "Não identificado"
                        tomador = "Não identificado"

                        if os.path.exists(caminho_pdf):
                            try:
                                reader = PdfReader(caminho_pdf)
                                texto_pdf = ""
                                for page in reader.pages: texto_pdf += page.extract_text()
                                texto_upper = texto_pdf.upper()

                                # 1. Valores
                                padrao_valor = r"R\$\s*([\d\.]+,\d{2})"
                                if "VALOR TOTAL DA NFS-E" in texto_upper:
                                    trecho = texto_upper.split("VALOR TOTAL DA NFS-E")[1][:200]
                                    match = re.search(padrao_valor, trecho)
                                    if match: val_servico = self.converter_valor_br(match.group(1))

                                if "VALOR LÍQUIDO DA NFS-E" in texto_upper:
                                    trecho = texto_upper.split("VALOR LÍQUIDO DA NFS-E")[1][:200]
                                    match = re.search(padrao_valor, trecho)
                                    if match: val_liquido = self.converter_valor_br(match.group(1))

                                # 2. Data
                                match_dt_emi = re.search(r"DATA E HORA DA EMISSÃO.*(\d{2}/\d{2}/\d{4})", texto_upper,
                                                         re.IGNORECASE)
                                if match_dt_emi:
                                    data_emissao = match_dt_emi.group(1)
                                else:
                                    match_generic = re.search(r"(\d{2}/\d{2}/\d{4})", texto_upper)
                                    if match_generic: data_emissao = match_generic.group(1)

                                # 3. Número da NFS-e
                                match_num = re.search(r"NÚMERO DA NFS-E\s+(\d+)", texto_upper)
                                if match_num: numero_nf = match_num.group(1)

                                # 4. Entidades
                                if "TOMADOR DO SERVIÇO" in texto_upper:
                                    idx_tomador = texto_upper.find("TOMADOR DO SERVIÇO")
                                    bloco_prestador = texto_pdf[:idx_tomador]
                                    bloco_tomador = texto_pdf[idx_tomador:]
                                    prestador = self.extrair_dados_entidade(bloco_prestador)
                                    tomador = self.extrair_dados_entidade(bloco_tomador)

                            except Exception as e_pdf:
                                print(f"Erro leitura PDF: {e_pdf}")

                        # Regras
                        if val_servico > 0 and val_liquido == 0: val_liquido = val_servico
                        if val_liquido > 0 and val_servico == 0: val_servico = val_liquido

                        if val_servico > val_liquido:
                            retencao = "SIM"
                        else:
                            retencao = "NÃO"

                        # --- EXCEL FINAL (Ordenado) ---
                        dados_excel.append({
                            "Data Emissão": data_emissao,
                            "Número NFS-e": numero_nf,
                            "Prestador": prestador,
                            "Tomador": tomador,
                            "Valor Serviço (R$)": val_servico,
                            "Valor Líquido (R$)": val_liquido,
                            "RETENÇÃO": retencao,
                            "Status": subpasta
                        })

                        # Mover
                        pasta_destino = os.path.join(pasta_raiz, subpasta)
                        os.makedirs(pasta_destino, exist_ok=True)
                        if os.path.exists(caminho_pdf): shutil.move(caminho_pdf,
                                                                    os.path.join(pasta_destino, nome_base + ".pdf"))
                        if os.path.exists(caminho_xml): shutil.move(caminho_xml,
                                                                    os.path.join(pasta_destino, nome_base + ".xml"))

                    if dados_excel:
                        try:
                            df = pd.DataFrame(dados_excel)
                            nome_excel = f"Relatorio_Contabil_{datetime.now().strftime('%d%m%Y_%H%M')}.xlsx"
                            # CORREÇÃO: Salvar direto na pasta raiz (pasta_raiz)
                            caminho_final_excel = os.path.join(pasta_raiz, nome_excel)

                            df.to_excel(caminho_final_excel, index=False)
                            log_func(f"Excel Contábil gerado em: {pasta_raiz}", "sucesso")
                        except Exception as e_ex:
                            log_func(f"Erro Excel: {e_ex}", "erro")

                if self.parar_solicitado:
                    log_func("PROCESSO INTERROMPIDO.", "erro")
                else:
                    log_func("Concluído!", "sucesso")
                messagebox.showinfo("Sistema", "Finalizado.")
        except Exception as e:
            log_func(f"ERRO GERAL: {str(e)}", "erro")

    def tela_nfse(self):
        self.parent.limpar_tela()
        f_l = tk.Frame(self.container, pady=10);
        f_l.pack();
        self.parent.carregar_logo(f_l)
        hoje = date.today()
        if hoje.month == 1:
            mes_ant, ano_ant = 12, hoje.year - 1
        else:
            mes_ant, ano_ant = hoje.month - 1, hoje.year
        dt_ini = date(ano_ant, mes_ant, 1).strftime("%d/%m/%Y")
        dt_fim = date(ano_ant, mes_ant, calendar.monthrange(ano_ant, mes_ant)[1]).strftime("%d/%m/%Y")

        frame_config = tk.LabelFrame(self.container, text=" Configuração ", padx=15, pady=15)
        frame_config.pack(padx=20, pady=10, fill="x")
        f_datas = tk.Frame(frame_config);
        f_datas.pack(fill="x", pady=5)
        tk.Label(f_datas, text="Início:").grid(row=0, column=0)
        self.ent_data_ini = tk.Entry(f_datas, width=12);
        self.ent_data_ini.grid(row=0, column=1, padx=5);
        self.ent_data_ini.insert(0, dt_ini)
        tk.Label(f_datas, text="Fim:").grid(row=0, column=2, padx=10)
        self.ent_data_fim = tk.Entry(f_datas, width=12);
        self.ent_data_fim.grid(row=0, column=3, padx=5);
        self.ent_data_fim.insert(0, dt_fim)

        tk.Label(frame_config, text="Pasta Salvar:").pack(anchor="w", pady=(10, 0))
        f_path = tk.Frame(frame_config);
        f_path.pack(fill="x")
        self.ent_caminho = tk.Entry(f_path, font=("Arial", 10));
        self.ent_caminho.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))
        self.ent_caminho.insert(0, self.parent.configuracoes.get("ultimo_caminho", ""))
        tk.Button(f_path, text="Selecionar", command=self.selecionar_pasta).pack(side=tk.RIGHT)

        self.parent.txt_log = scrolledtext.ScrolledText(self.container, width=125, height=15, state='disabled',
                                                        font=("Consolas", 9))
        self.parent.txt_log.pack(padx=20, pady=5)

        f_btns = tk.Frame(self.container, pady=10);
        f_btns.pack()
        tk.Button(f_btns, text="1. ACESSAR", command=lambda: self.abrir_portal_nacional(self.parent.log_msg),
                  bg="#005A9C", fg="white", font=("Arial", 9, "bold"), height=2, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(f_btns, text="2. DESTINADAS", command=lambda: self.iniciar_automacao_geral(self.parent.log_msg, 1),
                  bg="#228B22", fg="white", font=("Arial", 9, "bold"), height=2, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(f_btns, text="3. EMITIDAS", command=lambda: self.iniciar_automacao_geral(self.parent.log_msg, 2),
                  bg="#f39200", fg="white", font=("Arial", 9, "bold"), height=2, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(f_btns, text="PARAR", command=self.interromper_processo, bg="#CC0000", fg="white",
                  font=("Arial", 9, "bold"), height=2, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(f_btns, text="Voltar", command=self.parent.mostrar_menu_inicial, bg="#666", fg="white",
                  font=("Arial", 9, "bold"), height=2, width=10).pack(side=tk.LEFT, padx=5)