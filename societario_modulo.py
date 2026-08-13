import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import requests
import json
import re
import webbrowser
from datetime import datetime


class SocietarioModulo:
    """
    Consulta de CNPJ via publica.cnpj.ws
    Integrado ao menu principal do Emissor Abentroth.
    """

    API_URL = "https://publica.cnpj.ws/cnpj/{cnpj}"

    def __init__(self, parent):
        self.parent = parent
        self._dados = {}
        self._campos = 0
        self._cnpj_atual = ""

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def tela_societario(self):
        self.parent.limpar_tela()
        self._json_visivel = False

        f_head = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_head.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(f_head, text="🏢 Consulta Societária — CNPJ",
                     font=("Arial", 20, "bold"), text_color="#1f538d").pack()
        ctk.CTkLabel(f_head,
                     text="Dados oficiais via Receita Federal  •  publica.cnpj.ws  •  "
                          "compatível com CNPJ alfanumérico",
                     font=("Arial", 11), text_color="gray").pack()

        f_busca = ctk.CTkFrame(self.parent.container)
        f_busca.pack(fill="x", padx=40, pady=6)

        f_inner = ctk.CTkFrame(f_busca, fg_color="transparent")
        f_inner.pack(pady=12, padx=20)

        ctk.CTkLabel(f_inner, text="CNPJ:", font=("Arial", 12, "bold"),
                     width=50, anchor="w").pack(side="left")

        self.ent_cnpj = ctk.CTkEntry(
            f_inner, placeholder_text="00.000.000/0000-00 (ou alfanumérico)",
            width=220, font=("Arial", 13), height=36)
        self.ent_cnpj.pack(side="left", padx=8)
        self.ent_cnpj.bind("<KeyRelease>", self._mascara_cnpj)
        self.ent_cnpj.bind("<Return>", lambda e: self._consultar())

        self.btn_consultar = ctk.CTkButton(
            f_inner, text="🔍  Consultar", width=130, height=36,
            font=("Arial", 12, "bold"),
            fg_color="#1f538d", hover_color="#14375e",
            command=self._consultar)
        self.btn_consultar.pack(side="left", padx=4)

        ctk.CTkButton(
            f_inner, text="✖ Limpar", width=90, height=36,
            font=("Arial", 11), fg_color="#7f8c8d", hover_color="#626d70",
            command=self._limpar).pack(side="left", padx=4)

        f_status = ctk.CTkFrame(f_busca, fg_color="transparent")
        f_status.pack(fill="x", padx=20, pady=(0, 8))
        self.lbl_status = ctk.CTkLabel(
            f_status, text="", font=("Arial", 11), text_color="gray")
        self.lbl_status.pack(side="left")
        self.lbl_contador = ctk.CTkLabel(
            f_status, text="", font=("Arial", 11), text_color="#1f538d")
        self.lbl_contador.pack(side="right")

        self.f_resultado = ctk.CTkFrame(
            self.parent.container, fg_color="transparent")
        self.f_resultado.pack(fill="both", expand=True, padx=40, pady=4)

        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=8)

        self.btn_json = ctk.CTkButton(
            f_btns, text="{ } Ver JSON Bruto", width=150, height=38,
            font=("Arial", 11, "bold"),
            fg_color="#2c3e50", hover_color="#1a252f",
            command=self._toggle_json, state="disabled")
        self.btn_json.pack(side="left", padx=6)

        self.btn_copiar = ctk.CTkButton(
            f_btns, text="⎘ Copiar JSON", width=130, height=38,
            font=("Arial", 11, "bold"),
            fg_color="#27ae60", hover_color="#1e8449",
            command=self._copiar_json, state="disabled")
        self.btn_copiar.pack(side="left", padx=6)

        ctk.CTkButton(
            f_btns, text="Voltar", width=100, height=38,
            fg_color="gray", hover_color="darkgray",
            command=self.parent.mostrar_menu_inicial).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Máscara CNPJ (numérico ou alfanumérico — Receita Federal, RFB a partir de 07/2026)
    # ------------------------------------------------------------------
    def _limpar_cnpj(self, texto: str) -> str:
        """Remove máscara e mantém só caracteres alfanuméricos (até 14), maiúsculo."""
        return re.sub(r'[^A-Za-z0-9]', '', str(texto)).upper()[:14]

    def _mascara_cnpj(self, event=None):
        teclas_ok = {"BackSpace", "Delete", "Left", "Right", "Tab", "Home", "End"}
        if event and event.keysym in teclas_ok:
            return
        texto = self.ent_cnpj.get()
        chars = self._limpar_cnpj(texto)
        r = ""
        for i, c in enumerate(chars):
            if i == 2:
                r += "."
            elif i == 5:
                r += "."
            elif i == 8:
                r += "/"
            elif i == 12:
                r += "-"
            r += c
        if texto != r:
            self.ent_cnpj.delete(0, tk.END)
            self.ent_cnpj.insert(0, r)

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    def _consultar_simples_playwright(self, cnpj: str) -> dict:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {}

        try:
            with sync_playwright() as p:
                # Lançamos com argumentos para disfarçar a automação
                browser = p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
                )

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                )

                page = context.new_page()
                # Adiciona um script para ocultar que é automação
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                page.goto(
                    "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATBHE/ConsultaOptantes.app/ConsultarOpcao.html",
                    wait_until="domcontentloaded", timeout=40000)

                # Simula um pequeno tempo de carregamento
                time.sleep(3)

                cnpj_fmt = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"

                # Preenche e clica com tentativa extra de busca
                page.fill("input[id*='cnpj']", cnpj_fmt)
                page.click("button:has-text('Consultar')")

                # Espera 8 segundos para carregar o resultado
                try:
                    page.wait_for_selector("#resultado, .alert-warning", timeout=8000)
                except:
                    pass

                # Captura o texto total
                texto = page.content()
                browser.close()

                # Análise (agora mais tolerante a variações)
                sn_opt = None
                mei_opt = None

                # Verificação de texto
                if re.search(r'Optante pelo Simples Nacional', texto, re.I):
                    sn_opt = True
                elif re.search(r'N[ÃA]O\s+(optante|enquadrado)', texto, re.I):
                    sn_opt = False

                if re.search(r'N[ÃA]O enquadrado no SIMEI', texto, re.I):
                    mei_opt = False
                elif re.search(r'Optante pelo SIMEI|enquadrado no SIMEI', texto, re.I):
                    mei_opt = True

                data_opcao = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if (
                    m := re.search(r'desde\s+(\d{2})/(\d{2})/(\d{4})', texto, re.I)) else None

                # Se a API retornou um texto de "serviço indisponível" ou "erro", retornamos vazio
                if "503" in texto or "service unavailable" in texto.lower():
                    return {}

                return {
                    "fonte": "Portal Simples Nacional (RF)",
                    "sn_optante": sn_opt,
                    "mei_optante": mei_opt,
                    "data_opcao_sn": data_opcao,
                    "data_exclusao_sn": None,
                    "data_opcao_mei": None,
                    "data_exclusao_mei": None,
                    "regime": None,
                }
        except Exception as e:
            print(f"Erro Playwright: {e}")
            return {}

    def _consultar(self):
        cnpj = self._limpar_cnpj(self.ent_cnpj.get())
        if len(cnpj) != 14:
            messagebox.showwarning(
                "CNPJ Inválido",
                "Digite um CNPJ com 14 caracteres (numérico ou alfanumérico).")
            return

        self._cnpj_atual = cnpj  # ← salva agora, antes de qualquer coisa
        self._limpar_resultado()
        self.btn_consultar.configure(state="disabled", text="⏳ Consultando...")
        self.lbl_status.configure(text="Consultando Receita Federal...",
                                  text_color="#e67e22")
        self.btn_json.configure(state="disabled")
        self.btn_copiar.configure(state="disabled")

        threading.Thread(target=self._fazer_requisicao,
                         args=(cnpj,), daemon=True).start()

    def _fazer_requisicao(self, cnpj: str):
        try:
            resp = requests.get(
                self.API_URL.format(cnpj=cnpj),
                timeout=15,
                headers={"Accept": "application/json"})

            if resp.status_code == 200:
                dados = resp.json()

                # Verifica se simples veio nulo → busca AGORA no background (na thread certa)
                simples = dados.get("simples") or {}
                simei = dados.get("simei") or {}
                cnpj_alfanumerico = bool(re.search(r'[A-Za-z]', cnpj))
                if (simples.get("optante") is None and simei.get("optante") is None
                        and not cnpj_alfanumerico):
                    # Fontes alternativas (NFe.io, BrasilAPI, ReceitaWS) ainda não
                    # confirmaram suporte a CNPJ alfanumérico — pula para não gastar
                    # tempo com requisições que tendem a falhar.
                    self.parent.root.after(0, lambda: self.lbl_status.configure(
                        text="⏳ Consultando Simples Nacional nas fontes alternativas...",
                        text_color="#e67e22"))

                    fallback = self._consultar_simples_fallback(cnpj)
                    if fallback:
                        dados["_simples_fallback"] = fallback

                self.parent.root.after(0, lambda: self._exibir_resultado(dados))
            elif resp.status_code == 429:
                self.parent.root.after(0, lambda: self._erro(
                    "Muitas consultas. Aguarde e tente novamente."))
            elif resp.status_code == 404:
                self.parent.root.after(0, lambda: self._erro(
                    f"CNPJ {cnpj} não encontrado."))
            else:
                self.parent.root.after(0, lambda: self._erro(
                    f"Erro HTTP {resp.status_code}"))

        except requests.exceptions.ConnectionError:
            self.parent.root.after(0, lambda: self._erro("Sem conexão."))
        except Exception as e:
            self.parent.root.after(0, lambda: self._erro(f"Erro: {e}"))
        finally:
            self.parent.root.after(0, lambda: self.btn_consultar.configure(
                state="normal", text="🔍  Consultar"))

    def _erro(self, msg: str):
        self.lbl_status.configure(text=f"⚠ {msg}", text_color="#c0392b")

    def _limpar(self):
        self.ent_cnpj.delete(0, tk.END)
        self._limpar_resultado()
        self.lbl_status.configure(text="")
        self.lbl_contador.configure(text="")

    def _limpar_resultado(self):
        for w in self.f_resultado.winfo_children():
            w.destroy()
        self._dados = {}
        self._json_visivel = False
        self.btn_json.configure(state="disabled", text="{ } Ver JSON Bruto")
        self.btn_copiar.configure(state="disabled")

    # ------------------------------------------------------------------
    # Resultado
    # ------------------------------------------------------------------
    def _exibir_resultado(self, dados: dict):
        self._dados = dados
        est = dados.get("estabelecimento") or {}

        self._campos = self._contar_campos(dados)
        self.lbl_contador.configure(text=f"📊 {self._campos} campos preenchidos")

        situacao = (est.get("situacao_cadastral") or "").upper()
        cor_sit = ("#27ae60" if situacao == "ATIVA"
                   else "#c0392b" if situacao in ("BAIXADA", "INAPTA")
        else "#e67e22")

        self.lbl_status.configure(
            text=f"✅ {dados.get('razao_social', 'CNPJ consultado')}",
            text_color="#27ae60")
        self.btn_json.configure(state="normal")
        self.btn_copiar.configure(state="normal")

        f = self.f_resultado

        if not est:
            aviso = ctk.CTkFrame(f, fg_color="#7d3c00", corner_radius=8)
            aviso.pack(fill="x", pady=4)
            ctk.CTkLabel(aviso,
                         text="⚠️  Dados limitados — API não retornou 'estabelecimento' "
                              "(filial, entidade gov. ou tipo especial).",
                         font=("Arial", 10), text_color="white",
                         wraplength=580, justify="left").pack(padx=12, pady=8)

        simples = dados.get("simples") or {}
        simei = dados.get("simei") or {}
        self._card_simples(f, simples, simei)

        # Identificação
        self._card(f"📋 IDENTIFICAÇÃO", [
            ("Razão Social", dados.get("razao_social")),
            ("Nome Fantasia", est.get("nome_fantasia")),
            ("CNPJ", self._fmt_cnpj(est.get("cnpj"))),
            ("Situação Cadastral", situacao, cor_sit),
            ("Data Situação", self._fmt_data(est.get("data_situacao_cadastral"))),
            ("Data Abertura", self._fmt_data(est.get("data_inicio_atividade"))),
            ("Porte", (dados.get("porte") or {}).get("descricao")),
            ("Natureza Jurídica", (dados.get("natureza_juridica") or {}).get("descricao")),
            ("Capital Social", self._fmt_moeda(dados.get("capital_social"))),
        ])

        # Endereço
        logradouro = " ".join(filter(None, [
            est.get("tipo_logradouro"), est.get("logradouro"),
            est.get("numero"), est.get("complemento")]))
        cidade_uf = " / ".join(filter(None, [
            (est.get("cidade") or {}).get("nome"),
            (est.get("estado") or {}).get("sigla")]))

        self._card(f"📍 ENDEREÇO", [
            ("Logradouro", logradouro or None),
            ("Bairro", est.get("bairro")),
            ("CEP", self._fmt_cep(est.get("cep"))),
            ("Cidade / UF", cidade_uf or None),
            ("País", (est.get("pais") or {}).get("nome")),
        ])

        # CNAE
        cnae_p = est.get("atividade_principal") or {}
        linhas_cnae = [
            ("Principal", f"{cnae_p.get('id', '')} — {cnae_p.get('descricao', '')}"),
        ]
        for s in (est.get("atividades_secundarias") or []):
            linhas_cnae.append(("Secundária",
                                f"{s.get('id', '')} — {s.get('descricao', '')}"))
        self._card(f"⚙️ ATIVIDADES (CNAE)", linhas_cnae)

        # Contato
        self._card(f"📞 CONTATO", [
            ("Telefone 1", self._fmt_fone(est.get("ddd1"), est.get("telefone1"))),
            ("Telefone 2", self._fmt_fone(est.get("ddd2"), est.get("telefone2"))),
            ("Fax", self._fmt_fone(est.get("ddd_fax"), est.get("fax"))),
            ("E-mail", est.get("email")),
        ])

        # Quadro societário
        socios = dados.get("socios") or []
        if socios:
            linhas_s = []
            for s in socios:
                nome = s.get("nome") or s.get("razao_social") or ""
                qual = (s.get("qualificacao_socio") or {}).get("descricao", "")
                linhas_s.append((qual or "Sócio", nome))
            self._card(f"👥 QUADRO SOCIETÁRIO", linhas_s)

        # Inscrições estaduais
        inscricoes = est.get("inscricoes_estaduais") or []
        if inscricoes:
            linhas_ie = []
            for ie in inscricoes:
                uf = (ie.get("estado") or {}).get("sigla", "?")
                num = ie.get("inscricao_estadual", "")
                ativo = "Ativa" if ie.get("ativo") else "Inativa"
                linhas_ie.append((f"IE — {uf}", f"{num}  ({ativo})"))
            self._card(f"📄 INSCRIÇÕES ESTADUAIS", linhas_ie)

        self._secao_dinamica(f, dados)

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def _card(self, titulo: str, linhas: list):
        frame = ctk.CTkFrame(self.f_resultado)
        frame.pack(fill="x", pady=5)

        ctk.CTkLabel(frame, text=titulo,
                     font=("Arial", 11, "bold"), text_color="white",
                     fg_color="#1f538d", corner_radius=0,
                     anchor="w").pack(fill="x", ipadx=10, ipady=4)

        for item in linhas:
            if len(item) == 2:
                lbl_txt, val = item
                cor_val = None
            else:
                lbl_txt, val, cor_val = item

            if not val and val != 0:
                continue

            f_linha = ctk.CTkFrame(frame, fg_color="transparent")
            f_linha.pack(fill="x", padx=12, pady=1)

            ctk.CTkLabel(f_linha, text=f"{lbl_txt}:",
                         font=("Arial", 10, "bold"),
                         width=160, anchor="w",
                         text_color="#555555").pack(side="left")

            self._valor_copiavel(f_linha, str(val), cor=cor_val)

    def _card_simples(self, parent, simples: dict, simei: dict):
        """Card Simples Nacional — adaptado para o formato do publica.cnpj.ws"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=5)

        ctk.CTkLabel(frame, text="🏛️ SIMPLES NACIONAL / MEI",
                     font=("Arial", 11, "bold"), text_color="white",
                     fg_color="#1f538d", corner_radius=0,
                     anchor="w").pack(fill="x", ipadx=10, ipady=4)

        f_badges = ctk.CTkFrame(frame, fg_color="transparent")
        f_badges.pack(fill="x", padx=12, pady=10)

        # ── Ajuste de Lógica: Convertendo "Sim"/"Não" da API para True/False ────
        sn_opt = (simples.get("simples", "").lower() == "sim")
        mei_opt = (simples.get("mei", "").lower() == "sim")

        # Define as datas corretamente conforme o JSON da API
        data_opcao_sn = simples.get("data_opcao_simples")
        data_exclusao_sn = simples.get("data_exclusao_simples")

        if sn_opt is True:
            sn_txt, sn_cor = "✅  OPTANTE", "#27ae60"
        else:
            sn_txt, sn_cor = "❌  NÃO OPTANTE", "#c0392b"

        f_sn = ctk.CTkFrame(f_badges, fg_color=sn_cor, corner_radius=8)
        f_sn.pack(side="left", padx=(0, 16), ipadx=20, ipady=10)
        ctk.CTkLabel(f_sn, text="Simples Nacional",
                     font=("Arial", 9), text_color="white").pack(pady=(4, 0))
        ctk.CTkLabel(f_sn, text=sn_txt,
                     font=("Arial", 15, "bold"), text_color="white").pack(pady=(0, 4))

        if mei_opt is True:
            mei_txt, mei_cor = "✅  MEI ATIVO", "#2980b9"
        else:
            mei_txt, mei_cor = "❌  NÃO É MEI", "#7f8c8d"

        f_mei = ctk.CTkFrame(f_badges, fg_color=mei_cor, corner_radius=8)
        f_mei.pack(side="left", ipadx=20, ipady=10)
        ctk.CTkLabel(f_mei, text="MEI",
                     font=("Arial", 9), text_color="white").pack(pady=(4, 0))
        ctk.CTkLabel(f_mei, text=mei_txt,
                     font=("Arial", 15, "bold"), text_color="white").pack(pady=(0, 4))

        # ── Datas ──────────────────────────────────────────────────────────
        datas = [
            ("Data Opção SN", data_opcao_sn),
            ("Data Exclusão SN", data_exclusao_sn),
            ("Última Atualiz.", simples.get("atualizado_em")),
        ]
        for lbl, val in datas:
            if not val:
                continue
            f_linha = ctk.CTkFrame(frame, fg_color="transparent")
            f_linha.pack(fill="x", padx=12, pady=1)
            ctk.CTkLabel(f_linha, text=f"{lbl}:",
                         font=("Arial", 10, "bold"),
                         width=160, anchor="w",
                         text_color="#555555").pack(side="left")

            # Formata a data se for string ISO (YYYY-MM-DD...)
            valor_formatado = self._fmt_data(str(val)[:10]) if "data" in lbl.lower() else str(val)
            self._valor_copiavel(f_linha, valor_formatado)

    # ------------------------------------------------------------------
    # Seção dinâmica
    # ------------------------------------------------------------------
    def _secao_dinamica(self, parent, dados: dict):
        tem_est = bool(dados.get("estabelecimento"))
        IGNORAR = {
            "razao_social", "capital_social", "porte", "natureza_juridica",
            "simples", "simei", "socios", "estabelecimento",
        } if tem_est else set()

        extras = {k: v for k, v in dados.items()
                  if k not in IGNORAR and v not in (None, "", [], {})}
        if not extras:
            return

        titulo = "📋 TODOS OS DADOS DISPONÍVEIS" if not tem_est else "🔍 DADOS ADICIONAIS"
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=5)
        ctk.CTkLabel(frame, text=titulo,
                     font=("Arial", 11, "bold"), text_color="white",
                     fg_color="#2c3e50", corner_radius=0,
                     anchor="w").pack(fill="x", ipadx=10, ipady=4)

        for chave, valor in extras.items():
            self._renderizar_campo(frame, chave, valor, nivel=0)

    def _renderizar_campo(self, parent, chave: str, valor, nivel: int = 0):
        nome = chave.replace("_", " ").title()
        pad = 12 + nivel * 16

        if isinstance(valor, dict):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=pad, pady=2)
            ctk.CTkLabel(f, text=f"▸ {nome}",
                         font=("Arial", 10, "bold"),
                         text_color="#1f538d").pack(anchor="w")
            for k, v in valor.items():
                if v not in (None, "", [], {}):
                    self._renderizar_campo(parent, k, v, nivel + 1)

        elif isinstance(valor, list):
            if not valor:
                return
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=pad, pady=2)
            ctk.CTkLabel(f, text=f"▸ {nome} ({len(valor)} item(s))",
                         font=("Arial", 10, "bold"),
                         text_color="#1f538d").pack(anchor="w")
            for i, item in enumerate(valor):
                if isinstance(item, dict):
                    self._renderizar_campo(parent, f"Item {i + 1}", item, nivel + 1)
                else:
                    self._linha_simples(parent, f"  [{i + 1}]", item, pad + 16)
        else:
            self._linha_simples(parent, nome, valor, pad)

    def _linha_simples(self, parent, nome: str, valor, pad: int):
        val_str = self._formatar_valor(nome, valor)
        if not val_str:
            return
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=pad, pady=1)
        ctk.CTkLabel(f, text=f"{nome}:",
                     font=("Arial", 10, "bold"),
                     width=160, anchor="w",
                     text_color="#555555").pack(side="left")
        self._valor_copiavel(f, val_str)

    # ------------------------------------------------------------------
    # Fallback Simples Nacional
    # ------------------------------------------------------------------
    def _consultar_simples_fallback(self, cnpj: str) -> dict:
        """Consulta SN via NFe.io → BrasilAPI → ReceitaWS."""

        # 1 — NFe.io
        try:
            r = requests.get(
                f"https://legalentity.api.nfe.io/v1/legalentities/taxregime/{cnpj}",
                timeout=10, headers={"Accept": "application/json"})
            if r.status_code == 200:
                d = r.json()
                regime = d.get("taxRegime", "")
                sn_opt = regime == "SimplesNacional"
                mei_opt = regime == "Mei"
                opted = d.get("optedInOn", "")[:10] if d.get("optedInOn") else None
                exclusao = None
                for p in (d.get("previousDetails") or []):
                    if p.get("endOn"):
                        exclusao = p["endOn"][:10]
                        break
                return {
                    "fonte": "NFe.io / Receita Federal",
                    "sn_optante": sn_opt,
                    "mei_optante": mei_opt,
                    "data_opcao_sn": opted,
                    "data_exclusao_sn": exclusao,
                    "data_opcao_mei": opted if mei_opt else None,
                    "data_exclusao_mei": None,
                    "regime": regime,
                }
        except Exception:
            pass

        # 2 — BrasilAPI
        try:
            r = requests.get(
                f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
                timeout=10, headers={"Accept": "application/json"})
            if r.status_code == 200:
                d = r.json()
                sn = d.get("opcao_pelo_simples")
                mei = d.get("opcao_pelo_mei")
                if sn is not None or mei is not None:
                    return {
                        "fonte": "BrasilAPI",
                        "sn_optante": sn,
                        "mei_optante": mei,
                        "data_opcao_sn": d.get("data_opcao_pelo_simples"),
                        "data_exclusao_sn": d.get("data_exclusao_do_simples"),
                        "data_opcao_mei": d.get("data_opcao_pelo_mei"),
                        "data_exclusao_mei": d.get("data_exclusao_do_mei"),
                        "regime": None,
                    }
        except Exception:
            pass

        # 3 — ReceitaWS
        try:
            r = requests.get(
                f"https://receitaws.com.br/v1/cnpj/{cnpj}",
                timeout=10, headers={"Accept": "application/json"})
            if r.status_code == 200:
                d = r.json()
                sn_str = str(d.get("simples") or "").upper().strip(" .")
                if sn_str in ("SIM", "NÃO", "NAO"):
                    return {
                        "fonte": "ReceitaWS",
                        "sn_optante": sn_str == "SIM",
                        "mei_optante": None,
                        "data_opcao_sn": None,
                        "data_exclusao_sn": None,
                        "data_opcao_mei": None,
                        "data_exclusao_mei": None,
                        "regime": None,
                    }
        except Exception:
            pass

        return {}

    # ------------------------------------------------------------------
    # JSON bruto
    # ------------------------------------------------------------------
    def _toggle_json(self):
        if self._json_visivel:
            if hasattr(self, "_frame_json"):
                self._frame_json.destroy()
            self._json_visivel = False
            self.btn_json.configure(text="{ } Ver JSON Bruto")
        else:
            self._frame_json = ctk.CTkFrame(self.f_resultado)
            self._frame_json.pack(fill="x", pady=5)
            ctk.CTkLabel(self._frame_json, text="{ } JSON BRUTO",
                         font=("Arial", 11, "bold"), text_color="white",
                         fg_color="#2c3e50", corner_radius=0,
                         anchor="w").pack(fill="x", ipadx=10, ipady=4)
            txt = scrolledtext.ScrolledText(
                self._frame_json, height=20,
                bg="#1e1e1e", fg="#00ff88",
                font=("Consolas", 9), state="normal")
            txt.pack(fill="x", padx=8, pady=8)
            txt.insert("1.0", json.dumps(self._dados, ensure_ascii=False, indent=2))
            txt.configure(state="disabled")
            self._json_visivel = True
            self.btn_json.configure(text="✖ Ocultar JSON")

    def _copiar_json(self):
        if not self._dados:
            return
        self.parent.root.clipboard_clear()
        self.parent.root.clipboard_append(
            json.dumps(self._dados, ensure_ascii=False, indent=2))
        self.btn_copiar.configure(text="✔ Copiado!")
        self.parent.root.after(
            2000, lambda: self.btn_copiar.configure(text="⎘ Copiar JSON"))

    # ------------------------------------------------------------------
    # Widget copiável
    # ------------------------------------------------------------------
    def _valor_copiavel(self, parent, texto: str, cor=None):
        modo = ctk.get_appearance_mode()
        bg = "#2b2b2b" if modo == "Dark" else "#f9f9f9"
        fg = cor or ("white" if modo == "Dark" else "#1a1a1a")
        e = tk.Entry(parent, font=("Arial", 10), relief="flat", bd=0,
                     bg=bg, fg=fg, readonlybackground=bg,
                     state="readonly", cursor="xterm")
        e.configure(state="normal")
        e.insert(0, str(texto))
        e.configure(state="readonly")
        e.pack(side="left", padx=(4, 2), fill="x", expand=True)

        hover = "#3a3a3a" if modo == "Dark" else "#e2e2e2"
        btn_copy = ctk.CTkButton(
            parent, text="📋", width=24, height=22, corner_radius=4,
            font=("Arial", 11), fg_color="transparent",
            hover_color=hover, text_color="#1f538d")
        btn_copy.configure(command=lambda: self._copiar_valor(str(texto), btn_copy))
        btn_copy.pack(side="left", padx=(0, 4))
        return e

    def _copiar_valor(self, texto: str, btn=None):
        """Copia apenas o valor da linha (sem o rótulo) para a área de transferência."""
        self.parent.root.clipboard_clear()
        self.parent.root.clipboard_append(texto)
        if btn is not None:
            def _restaurar():
                try:
                    btn.configure(text="📋")
                except tk.TclError:
                    pass  # a linha pode ter sido destruída (limpar/nova consulta)
            btn.configure(text="✔")
            self.parent.root.after(1000, _restaurar)

    # ------------------------------------------------------------------
    # Formatadores
    # ------------------------------------------------------------------
    def _fmt_cnpj(self, v):
        if not v: return None
        d = re.sub(r'[^A-Za-z0-9]', '', str(v)).upper()
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else v

    def _fmt_cep(self, v):
        if not v: return None
        d = re.sub(r'\D', '', str(v))
        return f"{d[:5]}-{d[5:]}" if len(d) == 8 else v

    def _fmt_data(self, v):
        if not v: return None
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(v))
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else v

    def _fmt_moeda(self, v):
        if v is None: return None
        try:
            return (f"R$ {float(v):,.2f}"
                    .replace(",", "X").replace(".", ",").replace("X", "."))
        except Exception:
            return str(v)

    def _fmt_bool(self, v):
        if v is None: return None
        return "Sim" if v else "Não"

    def _fmt_fone(self, ddd, fone):
        if not fone: return None
        ddd = str(ddd or "").strip()
        fone = str(fone).strip()
        return f"({ddd}) {fone}" if ddd else fone

    def _formatar_valor(self, nome: str, valor) -> str:
        if valor is None or valor == "": return ""
        nl = nome.lower()
        if isinstance(valor, bool): return "Sim" if valor else "Não"
        s = str(valor)
        if "data" in nl or "date" in nl: return self._fmt_data(s) or s
        if "cnpj" in nl or "cpf" in nl:
            d = re.sub(r'[^A-Za-z0-9]', '', s).upper()
            if len(d) == 14: return self._fmt_cnpj(s)
            if len(d) == 11: return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
        if "cep" in nl:     return self._fmt_cep(s)
        if "capital" in nl: return self._fmt_moeda(s)
        return s

    def _contar_campos(self, obj, _vis=None) -> int:
        if _vis is None: _vis = set()
        oid = id(obj)
        if oid in _vis: return 0
        _vis.add(oid)
        count = 0
        if isinstance(obj, dict):
            for v in obj.values():
                if v not in (None, "", [], {}):
                    count += 1 + self._contar_campos(v, _vis)
        elif isinstance(obj, list):
            for item in obj:
                count += self._contar_campos(item, _vis)
        return count