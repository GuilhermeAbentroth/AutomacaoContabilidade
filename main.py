import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, simpledialog
import os
import sys
import json
import traceback
import threading
from datetime import datetime
from fiscal_api_modulo import FiscalAPIModulo

from licenca_modulo import LicencaModulo
from atualizador_modulo import AtualizadorModulo
from utils import isolar_scroll_mouse
from versao import VERSAO

try:
    from PIL import Image, ImageTk

    TEM_PILLOW = True
except ImportError:
    TEM_PILLOW = False
    print("AVISO: Biblioteca 'Pillow' não instalada.")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    caminho = os.path.join(base_path, relative_path)
    if os.path.exists(caminho): return caminho
    return os.path.join(base_path, "assets", relative_path)


from contabil_modulo import ContabilModulo
from fiscal_modulo import FiscalModulo
from nfse_modulo import PortalNacionalModulo
from betha_modulo import EmissorBethaModulo
from logger_utils import AutomationLogger
from betha_certificado_modulo import EmissorBethaCertificado
from betha_manual_modulo import EmissorBethaManual
from emissor_portal_nacional_modulo import EmissorPortalNacional

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class SistemaUnificadoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Automação Abentroth v{VERSAO}")

        # Define um tamanho mínimo razoável e inicia maximizado, ocupando
        # toda a tela disponível (notebook 14" ou monitor 24"), evitando
        # que botões fiquem cortados fora da área visível.
        self.root.minsize(1000, 650)
        self.root.resizable(True, True)
        try:
            self.root.state("zoomed")  # Windows: maximiza respeitando a barra de tarefas
        except Exception:
            largura_tela = self.root.winfo_screenwidth()
            altura_tela = self.root.winfo_screenheight()
            self.root.geometry(f"{largura_tela}x{altura_tela}+0+0")

        if getattr(sys, 'frozen', False):
            self.pasta_exe = os.path.dirname(sys.executable)
        else:
            self.pasta_exe = os.path.dirname(os.path.abspath(__file__))

        self.root.report_callback_exception = self.tratar_erro_callback

        self.caminho_config = os.path.join(self.pasta_exe, "config_sistema.json")
        self.configuracoes = self.carregar_todas_configs()
        tema_salvo = self.configuracoes.get("tema", "System")
        ctk.set_appearance_mode(tema_salvo)

        try:
            self.root.iconbitmap(resource_path("ico.ico"))
        except:
            pass

        # CTkScrollableFrame em vez de CTkFrame: quando o conteúdo da tela
        # não cabe na altura disponível (ex.: notebook 14"), aparece uma
        # barra de rolagem vertical em vez de cortar botões fora da tela.
        self.container = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=10, pady=10)
        self._configurar_centralizacao_container()

        # Inicialização dos Módulos
        self.licenca = LicencaModulo(self)
        self.atualizador = AtualizadorModulo(self)

        if not self.licenca.verificar_e_autenticar():
            self.root.destroy()
            return

        self.atualizador.verificar_atualizacao()

        self.contabil = ContabilModulo(self)
        self.fiscal = FiscalModulo(self)
        self.nfse = PortalNacionalModulo(self)
        self.fiscal_api = FiscalAPIModulo(self)
        self.logger_automacao = AutomationLogger(self.pasta_exe)

        self.betha = EmissorBethaModulo(self)
        self.betha_cert = EmissorBethaCertificado(self)
        self.betha_manual = EmissorBethaManual(self)
        self.emissor_pn = EmissorPortalNacional(self)

        from societario_modulo import SocietarioModulo
        self.societario = SocietarioModulo(self)

        from livro_eletronico_modulo import LivroEletronicoModulo
        self.livro_eletronico = LivroEletronicoModulo(self)

        from estatisticas_modulo import EstatisticasModulo
        self.estatisticas = EstatisticasModulo(self)

        from pessoal_modulo import PessoalModulo
        self.pessoal = PessoalModulo(self)

        from reforma_tributaria_modulo import ReformaTributariaModulo
        self.reforma_tributaria = ReformaTributariaModulo(self)

        self.mostrar_menu_inicial()



    def resource_path(self, relative_path):
        return resource_path(relative_path)

    def carregar_imagem_ajustada(self, path_imagem, max_size=(300, 180)):
        if not TEM_PILLOW: return None
        if not os.path.exists(path_imagem):
            img = Image.new('RGB', max_size, color='#f0f0f0')
        else:
            try:
                img = Image.open(path_imagem)
            except Exception as e:
                print(f"Erro imagem: {e}")
                img = Image.new('RGB', max_size, color='#ffcccc')
        return ctk.CTkImage(light_image=img, dark_image=img, size=max_size)

    def carregar_todas_configs(self):
        padrao = {
            "ultimo_caminho": os.path.join(self.pasta_exe, "saida de arquivos"),
            "pasta_jpype": "",
            "pasta_playwright": "",
            "caminho_banco": os.path.join(self.pasta_exe, "dados_escritorio.db"),
            "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "velocidade": "1",
            "licenca": "",
            "pasta_pdfs": os.path.join(self.pasta_exe, "NFSe_PDFs"),
            "pasta_reinf": os.path.join(self.pasta_exe, "REINF")
        }
        if os.path.exists(self.caminho_config):
            try:
                with open(self.caminho_config, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                padrao.update(dados)
            except:
                pass
        return padrao

    def salvar_config(self, chave=None, valor=None):
        if chave and valor is not None: self.configuracoes[chave] = valor
        try:
            with open(self.caminho_config, "w", encoding="utf-8") as f:
                json.dump(self.configuracoes, f, indent=4)
        except:
            pass

    def licenca_valida(self):
        return self.licenca.licenca_valida()

    def obter_data_validade(self):
        return self.licenca.obter_data_validade()

    def verificar_acesso_modulo(self, comando_modulo):
        if self.licenca_valida():
            comando_modulo()
        else:
            messagebox.showerror("Acesso Negado", "Licença expirada ou inválida.")

    def _alternar_tema(self):
        modo_atual = self.configuracoes.get("tema", "System")
        novo_modo = "Light" if modo_atual == "Dark" else "Dark"
        ctk.set_appearance_mode(novo_modo)
        self.salvar_config("tema", novo_modo)
        # Atualiza o texto do botão
        self.mostrar_menu_inicial()

    def abrir_tela_licenca(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Licença")
        janela.geometry("400x250")
        janela.resizable(False, False)
        janela.transient(self.root)
        janela.grab_set()

        x = (janela.winfo_screenwidth() // 2) - 200
        y = (janela.winfo_screenheight() // 2) - 125
        janela.geometry(f"400x250+{x}+{y}")

        # Status atual
        validade_str = self.licenca.obter_data_validade() or "—"
        login_str = self.licenca.obter_login() or "—"

        ctk.CTkLabel(janela, text="🔑 Licença Ativa",
                     font=("Arial", 16, "bold"), text_color="#228B22").pack(pady=15)

        ctk.CTkLabel(janela, text=f"Usuário: {login_str}",
                     font=("Arial", 12)).pack()

        lbl_validade = ctk.CTkLabel(janela, text=f"Válida até: {validade_str}",
                                    font=("Arial", 12))
        lbl_validade.pack(pady=5)

        lbl_status = ctk.CTkLabel(janela, text="", font=("Arial", 11),
                                  text_color="#228B22")
        lbl_status.pack(pady=5)

        def atualizar_licenca():
            btn_atualizar.configure(state="disabled", text="Consultando...")
            lbl_status.configure(text="", text_color="#228B22")
            janela.update()

            login = self.licenca.obter_login()

            senha_cache = self.licenca._obter_senha_cache()
            validade, erro = self.licenca._validar_online(login, senha_cache)

            if erro:
                lbl_status.configure(text=f"❌ {erro}", text_color="#d32f2f")
            else:
                self.licenca._validade_atual = validade
                self.licenca._salvar_cache(login, validade, senha_cache)
                nova_data = validade.strftime("%d/%m/%Y")
                lbl_validade.configure(text=f"Válida até: {nova_data}")
                lbl_status.configure(text="✅ Licença atualizada com sucesso!")

            btn_atualizar.configure(state="normal", text="🔄 Atualizar Licença")

        f_btns = ctk.CTkFrame(janela, fg_color="transparent")
        f_btns.pack(pady=15)

        btn_atualizar = ctk.CTkButton(
            f_btns, text="🔄 Atualizar Licença",
            width=180, height=40, fg_color="#1f538d", hover_color="#14375e",
            command=atualizar_licenca
        )
        btn_atualizar.pack(side="left", padx=10)

        ctk.CTkButton(
            f_btns, text="Sair / Trocar Usuário",
            width=160, height=40, fg_color="#c0392b", hover_color="#962d22",
            command=lambda: [janela.destroy(), self.licenca.logout(), self.root.destroy()]
        ).pack(side="left", padx=10)

        ctk.CTkButton(janela, text="Fechar", width=100, height=35,
                      fg_color="gray", command=janela.destroy).pack()

    def mostrar_info_sistema(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Sobre")
        janela.geometry("450x300")
        info_texto = f"Autor: Guilherme Abentroth\nVersão: {VERSAO}\nData: 19/08/2026\n\n" \
                     "1. Alterações em Portal Nacional\n" \
                     "2. Acrescentado Módulo Reforma Tributária\n" \

        f_info = ctk.CTkFrame(janela, fg_color="transparent")
        f_info.pack(pady=20, padx=20, fill="both", expand=True)
        ctk.CTkLabel(f_info, text="Automação Abentroth", font=("Arial", 18, "bold")).pack()
        ctk.CTkLabel(f_info, text=info_texto, font=("Arial", 12), justify="left").pack(pady=10)
        ctk.CTkButton(f_info, text="Fechar", command=janela.destroy).pack()

    def abrir_tela_config(self):
        senha = simpledialog.askstring("Restrito", "Digite a senha de admin:", show='*')
        if senha != "579499":
            messagebox.showerror("Erro", "Senha incorreta!")
            return

        janela = ctk.CTkToplevel(self.root)
        janela.title("Configurações")
        janela.geometry("800x400")
        try:
            janela.after(200, lambda: janela.iconbitmap(resource_path("ico.ico")))
        except:
            pass
        janela.transient(self.root)
        janela.grab_set()

        f_main = ctk.CTkFrame(janela)
        f_main.pack(fill="both", expand=True, padx=20, pady=20)

        def criar_linha(txt, chave):
            f = ctk.CTkFrame(f_main, fg_color="transparent")
            f.pack(fill="x", pady=10)
            ctk.CTkLabel(f, text=txt, font=("Arial", 12, "bold"), width=150, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=self.configuracoes.get(chave, ""))
            ctk.CTkEntry(f, textvariable=var, width=450).pack(side=tk.LEFT, padx=10)

            def b():
                p = filedialog.askopenfilename() if "chrome" in chave else filedialog.askdirectory()
                if p: var.set(p)

            def ok(): self.salvar_config(chave, var.get()); messagebox.showinfo("OK", "Salvo!")

            ctk.CTkButton(f, text="...", command=b, width=40).pack(side=tk.LEFT, padx=5)
            ctk.CTkButton(f, text="OK", command=ok, width=50).pack(side=tk.LEFT)

        def criar_vel():
            f = ctk.CTkFrame(f_main, fg_color="transparent")
            f.pack(fill="x", pady=10)
            ctk.CTkLabel(f, text="Velocidade:", font=("Arial", 12, "bold"), width=150, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=self.configuracoes.get("velocidade", "1"))
            op = ctk.CTkOptionMenu(f, variable=var, values=["1", "2", "3"], width=100)
            op.pack(side=tk.LEFT, padx=10)

            def save_vel():
                self.salvar_config("velocidade", var.get())
                messagebox.showinfo("OK", "Salvo!")

            ctk.CTkButton(f, text="OK", command=save_vel, width=50).pack(side=tk.LEFT, padx=105)

        criar_linha("Caminho Banco (Rede):", "caminho_banco")
        criar_linha("Pasta JPype:", "pasta_jpype")
        criar_linha("Pasta Playwright:", "pasta_playwright")
        criar_linha("Chrome Path:", "chrome_path")
        criar_linha("Pasta PDFs NFS-e:", "pasta_pdfs")
        criar_linha("Pasta Cópias REINF:", "pasta_reinf")
        criar_vel()

        ctk.CTkButton(f_main, text="📊 Ver Estatísticas de Uso",
                      command=self.estatisticas.abrir_tela_estatisticas,
                      fg_color="#1f538d", width=220).pack(pady=15)

    def log_msg(self, message, tipo="info", divisor=False):
        if hasattr(self, 'txt_log') and self.txt_log.winfo_exists():
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.txt_log.config(state='normal')
            if divisor: self.txt_log.insert(tk.END, "\n" + "=" * 90 + "\n")
            tag = tipo if tipo in ["erro", "sucesso"] else "info"
            self.txt_log.tag_config("erro", foreground="red")
            self.txt_log.tag_config("sucesso", foreground="green")
            self.txt_log.insert(tk.END, f"[{timestamp}] {message}\n", tag)
            self.txt_log.see(tk.END)
            self.txt_log.config(state='disabled')
            self.root.update()

    def limpar_tela(self):
        for widget in self.container.winfo_children(): widget.destroy()

    def _configurar_centralizacao_container(self):
        """A CTkScrollableFrame da lib sempre ancora o conteúdo no topo (anchor='nw'),
        deixando uma área vazia enorme abaixo em telas com pouco conteúdo quando a
        janela está maximizada. Aqui recentralizamos verticalmente quando o conteúdo
        é menor que a área visível, e mantemos o comportamento normal de rolagem
        (ancorado no topo) quando o conteúdo é maior do que a área visível."""
        canvas = self.container._parent_canvas

        def _centralizar(event=None):
            canvas.update_idletasks()
            canvas_h = canvas.winfo_height()
            content_h = self.container.winfo_reqheight()
            y = max(0, (canvas_h - content_h) // 2)
            canvas.coords(self.container._create_window_id, 0, y)
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(canvas_h, content_h + y)))

        self.container.bind("<Configure>", lambda e: self.root.after_idle(_centralizar), add="+")
        canvas.bind("<Configure>", lambda e: self.root.after_idle(_centralizar), add="+")

    def carregar_logo(self, parent):
        path_logo = resource_path("logo.png")
        if os.path.exists(path_logo) and TEM_PILLOW:
            try:
                img_pil = Image.open(path_logo)
                w, h = img_pil.size
                self.img_logo = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(int(w / 3), int(h / 3)))
                ctk.CTkLabel(parent, text="", image=self.img_logo).pack()
            except:
                pass
        else:
            ctk.CTkLabel(parent, text="SISTEMA AUTOMAÇÃO", font=("Arial", 24, "bold")).pack()

    # -------------------------------------------------------------------------
    # MENU INICIAL
    # -------------------------------------------------------------------------
    def mostrar_menu_inicial(self):
        self.limpar_tela()
        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(fill="x", pady=10)

        if self.licenca_valida():
            validade_str = self.obter_data_validade()
            txt_licenca_top = f"🔑 Licença ativa até: {validade_str}" if validade_str else "🔑 Licença Ativa"
            cor_licenca_top = "#228B22"
        else:
            txt_licenca_top = "❌ Licença Expirada / Inválida"
            cor_licenca_top = "#d32f2f"

        ctk.CTkLabel(f_top, text=txt_licenca_top, font=("Arial", 12, "bold"), text_color=cor_licenca_top).pack(
            side="left", padx=15)

        ctk.CTkButton(f_top, text="🔑 Licença", command=self.abrir_tela_licenca, width=100, fg_color="transparent",
                      border_width=1).pack(side="right", padx=5)
        ctk.CTkButton(f_top, text="⚙ Config", command=self.abrir_tela_config, width=80, fg_color="transparent").pack(
            side="right", padx=5)
        ctk.CTkButton(f_top, text="ℹ️ Info", command=self.mostrar_info_sistema, width=80, fg_color="transparent").pack(
            side="right", padx=5)
        modo_atual = self.configuracoes.get("tema", "System")
        texto_tema = "☀️ Claro" if modo_atual == "Dark" else "🌙 Escuro"
        ctk.CTkButton(f_top, text=texto_tema, width=90, fg_color="transparent",
                      command=self._alternar_tema).pack(side="right", padx=5)

        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=40)
        self.carregar_logo(f_l)

        f_b = ctk.CTkFrame(self.container, fg_color="transparent")
        f_b.pack(pady=50)

        btn_w = 220
        btn_h = 80

        btn_fiscal = ctk.CTkButton(
            f_b,
            text="FISCAL",
            command=lambda: self.verificar_acesso_modulo(self.tela_fiscal),
            width=btn_w,
            height=btn_h,
            font=("Arial", 20, "bold"),
            fg_color="#228B22",
            hover_color="#228B22",  # Trava o fundo verde
            border_width=2,
            border_color="#228B22"  # Borda invisível inicial
        )
        btn_fiscal.grid(row=0, column=0, padx=20, pady=20)

        # Eventos de Hover do Fiscal
        btn_fiscal.bind("<Enter>", lambda e: btn_fiscal.configure(border_color=("black", "white")))
        btn_fiscal.bind("<Leave>", lambda e: btn_fiscal.configure(border_color="#228B22"))

        # === BOTÃO CONTÁBIL ===
        btn_contabil = ctk.CTkButton(
            f_b,
            text="CONTÁBIL",
            command=lambda: self.verificar_acesso_modulo(self.tela_contabil),
            width=btn_w,
            height=btn_h,
            font=("Arial", 20, "bold"),
            fg_color="#005A9C",
            hover_color="#005A9C",  # Trava o fundo azul
            border_width=2,
            border_color="#005A9C"  # Borda invisível inicial
        )
        btn_contabil.grid(row=0, column=1, padx=20, pady=20)

        # Eventos de Hover do Contábil
        btn_contabil.bind("<Enter>", lambda e: btn_contabil.configure(border_color=("black", "white")))
        btn_contabil.bind("<Leave>", lambda e: btn_contabil.configure(border_color="#005A9C"))

        btn_portal = ctk.CTkButton(
            f_b,
            text="PORTAL NACIONAL",
            command=lambda: self.verificar_acesso_modulo(self.nfse.nfse_api.tela_api),
            width=btn_w,
            height=btn_h,
            font=("Arial", 20, "bold"),
            fg_color="#f39200",
            hover_color="#f39200",  # Trava a cor de fundo no hover
            border_width=2,
            border_color="#f39200"  # Borda invisível inicial para não dar "solavanco" no layout
        )
        # 2. Posiciona o botão na Grid
        btn_portal.grid(row=0, column=2, padx=20, pady=20)

        # 3. Adiciona os eventos de detecção do mouse (Preto para tema Claro, Branco para tema Escuro)
        btn_portal.bind("<Enter>", lambda e: btn_portal.configure(border_color=("black", "white")))
        btn_portal.bind("<Leave>", lambda e: btn_portal.configure(border_color="#f39200"))

        btn_emissor = ctk.CTkButton(
            f_b,
            text="EMISSOR NFSE",
            command=lambda: self.verificar_acesso_modulo(self.tela_escolha_emissor),
            width=btn_w,
            height=btn_h,
            font=("Arial", 16, "bold"),
            fg_color="#27ae60",
            hover_color="#27ae60",  # Trava o fundo verde original do emissor
            border_width=2,
            border_color="#27ae60"  # Borda invisível inicial para manter estabilidade
        )
        btn_emissor.grid(row=1, column=0, padx=20, pady=20)

        # Eventos de Hover do Emissor NFSE
        btn_emissor.bind("<Enter>", lambda e: btn_emissor.configure(border_color=("black", "white")))
        btn_emissor.bind("<Leave>", lambda e: btn_emissor.configure(border_color="#27ae60"))

        btn_soc = ctk.CTkButton(
            f_b, text="🏢 SOCIETÁRIO",
            command=self.societario.tela_societario,
            width=btn_w, height=btn_h, font=("Arial", 16, "bold"),
            fg_color="#8e44ad", hover_color="#6c3483",
            border_width=2, border_color="#8e44ad"
        )
        btn_soc.grid(row=1, column=1, padx=20, pady=20)
        btn_soc.bind("<Enter>", lambda e: btn_soc.configure(border_color=("black", "white")))
        btn_soc.bind("<Leave>", lambda e: btn_soc.configure(border_color="#8e44ad"))

        btn_livro = ctk.CTkButton(
            f_b, text="📕 LIVRO ELETRÔNICO",
            command=self.livro_eletronico.tela_livro,
            width=btn_w, height=btn_h, font=("Arial", 16, "bold"),
            fg_color="#6c3483", hover_color="#512e5f",
            border_width=2, border_color="#6c3483"
        )
        btn_livro.grid(row=1, column=2, padx=20, pady=20)
        btn_livro.bind("<Enter>", lambda e: btn_livro.configure(border_color=("black", "white")))
        btn_livro.bind("<Leave>", lambda e: btn_livro.configure(border_color="#6c3483"))

        btn_pessoal = ctk.CTkButton(
            f_b, text="👥 PESSOAL",
            command=self.pessoal.abrir,
            width=btn_w, height=btn_h, font=("Arial", 16, "bold"),
            fg_color="#16a085", hover_color="#12876f",
            border_width=2, border_color="#16a085"
        )
        btn_pessoal.grid(row=2, column=0, padx=20, pady=20)
        btn_pessoal.bind("<Enter>", lambda e: btn_pessoal.configure(border_color=("black", "white")))
        btn_pessoal.bind("<Leave>", lambda e: btn_pessoal.configure(border_color="#16a085"))

        # === BOTÃO EMISSOR PORTAL NACIONAL ===
        # Emissão direto pela API oficial do Emissor Nacional (SEFIN),
        # obrigatória em Jaraguá do Sul a partir de 01/09/2026 e já usada
        # hoje para outras cidades conveniadas ao Ambiente Nacional.
        btn_emissor_pn = ctk.CTkButton(
            f_b, text="EMISSOR PORTAL NACIONAL",
            command=lambda: self.verificar_acesso_modulo(self.emissor_pn.tela_escolha_emissor_pn),
            width=btn_w, height=btn_h, font=("Arial", 14, "bold"),
            fg_color="#2980b9", hover_color="#2980b9",
            border_width=2, border_color="#2980b9"
        )
        btn_emissor_pn.grid(row=2, column=1, padx=20, pady=20)
        btn_emissor_pn.bind("<Enter>", lambda e: btn_emissor_pn.configure(border_color=("black", "white")))
        btn_emissor_pn.bind("<Leave>", lambda e: btn_emissor_pn.configure(border_color="#2980b9"))

        # === BOTÃO REFORMA TRIBUTÁRIA ===
        # Versão automatizada do Societário: consulta em lote a situação de
        # Simples Nacional de uma planilha de empresas.
        btn_reforma = ctk.CTkButton(
            f_b, text="⚖️ REFORMA TRIBUTÁRIA",
            command=self.reforma_tributaria.tela_reforma_tributaria,
            width=btn_w, height=btn_h, font=("Arial", 16, "bold"),
            fg_color="#b9770e", hover_color="#9c640c",
            border_width=2, border_color="#b9770e"
        )
        btn_reforma.grid(row=2, column=2, padx=20, pady=20)
        btn_reforma.bind("<Enter>", lambda e: btn_reforma.configure(border_color=("black", "white")))
        btn_reforma.bind("<Leave>", lambda e: btn_reforma.configure(border_color="#b9770e"))

        ctk.CTkLabel(self.container, text="Powered by: Guilherme Abentroth", font=("Arial", 12)).pack(side=tk.BOTTOM,
                                                                                                      anchor="w",
                                                                                                      padx=20, pady=20)

    # -------------------------------------------------------------------------
    # TELA DE ESCOLHA (LOTE VS MANUAL)
    # -------------------------------------------------------------------------
    def tela_escolha_emissor(self):
        self.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=20)
        self.carregar_logo(f_top)

        ctk.CTkLabel(self.container, text="Selecione o Modo de Emissão",
                     font=("Arial", 22, "bold"), text_color="#27ae60").pack(pady=10)

        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=40)

        ctk.CTkButton(f_btns, text="📊 EMISSÃO EM LOTE (EXCEL)",
                      command=self.betha_cert.tela_emissor_certificado,
                      width=400, height=80, font=("Arial", 18, "bold"),
                      fg_color="#1f538d", hover_color="#14375e").pack(pady=15)

        ctk.CTkButton(f_btns, text="✍️ EMISSÃO MANUAL (CADASTRO)",
                      command=self.betha_manual.tela_emissor_manual,
                      width=400, height=80, font=("Arial", 18, "bold"),
                      fg_color="#27ae60", hover_color="#1e8449").pack(pady=15)

        ctk.CTkButton(f_btns, text="Voltar Menu Principal", command=self.mostrar_menu_inicial,
                      width=400, height=80, fg_color="gray").pack(pady=30)

    # -------------------------------------------------------------------------
    # TELAS PADRONIZADAS COM CUSTOM TKINTER
    # -------------------------------------------------------------------------
    def construir_tela_unico_modelo(self, nome_banco, nome_imagem, cor_titulo, funcao_backend):
        self.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=20)
        ctk.CTkLabel(f_top, text=f"Importação {nome_banco}", font=("Arial", 22, "bold"), text_color=cor_titulo).pack()
        ctk.CTkLabel(f_top, text="Clique na imagem abaixo para selecionar o arquivo e iniciar.",
                     font=("Arial", 12)).pack()

        def bridge(lista):
            self.contabil.gerar_ofx(self.log_msg, lista)

        f_img = ctk.CTkFrame(self.container, fg_color="transparent")
        f_img.pack(pady=20)

        path_img = resource_path(nome_imagem)
        self.img_temp = self.carregar_imagem_ajustada(path_img, max_size=(350, 250))

        btn_img = ctk.CTkButton(
            f_img,
            text="",
            image=self.img_temp,
            command=lambda: funcao_backend(self.log_msg, bridge),
            fg_color="transparent",
            hover_color="#e0e0e0"
        )
        btn_img.pack()

        ctk.CTkLabel(f_img, text=f"Modelo Padrão {nome_banco}", font=("Arial", 12, "bold")).pack(pady=10)

        f_log = ctk.CTkFrame(self.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        ctk.CTkLabel(f_log, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=10, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="both", expand=True)
        isolar_scroll_mouse(self.txt_log)

        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)
        ctk.CTkButton(f_btns, text="Voltar", command=self.tela_contabil, fg_color="gray", hover_color="darkgray",
                      width=150, height=40).pack()

    def tela_escolha_stone(self):
        self.construir_tela_unico_modelo("Stone", "STONE.png", "#00A868", self.contabil.fluxo_stone)

    def tela_escolha_pagbank(self):
        self.construir_tela_unico_modelo("PagBank", "PAGBANK.png", "#8BC34A", self.contabil.fluxo_pagbank)

    def tela_escolha_infinitepay(self):
        self.construir_tela_unico_modelo("InfinitePay", "INFINITE.png", "#5A2D82", self.contabil.fluxo_infinitepay)

    def tela_escolha_mercadopago(self):
        self.construir_tela_unico_modelo("Mercado Pago", "MERCADOPAGO.png", "#00B1EA", self.contabil.fluxo_mercadopago)

    def tela_escolha_sicredi(self):
        self.construir_tela_unico_modelo("Sicredi", "SICREDI.png", "#32BC43", self.contabil.fluxo_sicredi)

    def tela_escolha_ailos(self):
        configs = [
            {"texto": "Ailos V1 (Padrão)", "img": "AILOS.png", "cmd": self.contabil.fluxo_ailos_v1},
            {"texto": "Ailos V2 (Viacredi)", "img": "AILOS2.png", "cmd": self.contabil.fluxo_ailos_v2},
            {"texto": "Ailos V3 (Viacredi Conta Corrente)", "img": "AILOS3.png", "cmd": self.contabil.fluxo_ailos_v3}
        ]
        self.criar_tela_multi_modelos("AILOS", "#005A9C", configs)

    def tela_escolha_itau(self):
        configs = [
            {"texto": "Itaú V1 (Conta Corrente)", "img": "ITAU.png", "cmd": self.contabil.fluxo_itau},
            {"texto": "Itaú V2 (Extrato Mensal)", "img": "ITAU2.png", "cmd": self.contabil.fluxo_itau_v2}
        ]
        self.criar_tela_multi_modelos("ITAÚ", "#EC7000", configs)

    def tela_escolha_bradesco(self):
        self.construir_tela_unico_modelo("Bradesco", "BRADESCO.png", "#cc092f", self.contabil.fluxo_bradesco)

    def tela_escolha_ifood(self):
        self.construir_tela_unico_modelo("iFood", "IFOOD.png", "#EA1D2C", self.contabil.fluxo_ifood)

    def tela_escolha_nubank(self):
        self.construir_tela_unico_modelo("Nubank", "NUBANK.png", "#8A05BE", self.contabil.fluxo_nubank)

    def tela_escolha_magalupay(self):
        self.construir_tela_unico_modelo("MagaluPay", "MAGALUPAY.png", "#0086FF", self.contabil.fluxo_magalupay)

    def tela_escolha_cresol(self):
        configs = [
            {"texto": "Cresol V1 (Padrão)", "img": "CRESOL.png", "cmd": self.contabil.fluxo_cresol},
            {"texto": "Cresol V2 (Extrato Consolidado)", "img": "CRESOL2.png", "cmd": self.contabil.fluxo_cresol_v2}
        ]
        self.criar_tela_multi_modelos("CRESOL", "#006B3F", configs)

    def tela_escolha_c6(self):
        self.construir_tela_unico_modelo("C6 Bank", "C6.png", "#242424", self.contabil.fluxo_c6)

    def tela_escolha_rendimento(self):
        self.construir_tela_unico_modelo("Rendimento", "RENDIMENTO.png", "#004A93", self.contabil.fluxo_rendimento)

    def criar_tela_multi_modelos(self, nome_banco, cor_titulo, funcoes):
        self.limpar_tela()

        f_top = ctk.CTkFrame(self.container, fg_color="transparent")
        f_top.pack(pady=15)
        ctk.CTkLabel(f_top, text=f"Selecione o Modelo do Extrato {nome_banco}", font=("Arial", 20, "bold"),
                     text_color=cor_titulo).pack()
        ctk.CTkLabel(f_top, text="Clique na imagem para iniciar o processamento", font=("Arial", 12)).pack()

        f_imgs = ctk.CTkFrame(self.container, fg_color="transparent")
        f_imgs.pack(pady=10)

        col = 0
        row = 0
        self._img_refs = []

        def bridge(lista):
            self.contabil.gerar_ofx(self.log_msg, lista)

        for cfg in funcoes:
            f_op = ctk.CTkFrame(f_imgs, fg_color="transparent")
            f_op.grid(row=row, column=col, padx=20, pady=10)

            img_ctk = self.carregar_imagem_ajustada(resource_path(cfg["img"]), max_size=(250, 150))
            self._img_refs.append(img_ctk)

            cmd = lambda c=cfg["cmd"]: c(self.log_msg, bridge)
            btn = ctk.CTkButton(f_op, text="", image=img_ctk, command=cmd, fg_color="transparent",
                                hover_color="#e0e0e0")
            btn.pack()

            ctk.CTkLabel(f_op, text=cfg["texto"], font=("Arial", 12, "bold")).pack(pady=5)

            col += 1
            if col > 1:
                col = 0
                row += 1

        f_log = ctk.CTkFrame(self.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        ctk.CTkLabel(f_log, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=8, state='disabled', bg="#1e1e1e", fg="white",
                                                 font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="both", expand=True)
        isolar_scroll_mouse(self.txt_log)

        ctk.CTkButton(self.container, text="Voltar", command=self.tela_contabil, fg_color="gray",
                      hover_color="darkgray", width=150, height=40).pack(pady=15)

    def tela_escolha_caixa(self):
        configs = [
            {"texto": "Caixa V1 (Antigo)", "img": "CAIXA.png", "cmd": self.contabil.fluxo_caixa_v1},
            {"texto": "Caixa V2 (Horizontal)", "img": "CAIXA2.png", "cmd": self.contabil.fluxo_caixa_v2_horizontal},
            {"texto": "Caixa V2 (Vertical)", "img": "CAIXA2.png", "cmd": self.contabil.fluxo_caixa_v2_vertical},
            {"texto": "Caixa V3 (D/C)", "img": "CAIXA3.png", "cmd": self.contabil.fluxo_caixa_v3}
        ]
        self.criar_tela_multi_modelos("CAIXA", "#005CA9", configs)

    def tela_escolha_santander(self):
        configs = [
            {"texto": "Santander (Padrão)", "img": "SANTANDER.png", "cmd": self.contabil.fluxo_santander_v1},
            {"texto": "Santander (Empresas)", "img": "SANTANDER2.png", "cmd": self.contabil.fluxo_santander_v2}
        ]
        self.criar_tela_multi_modelos("SANTANDER", "#ec0000", configs)

    def tela_escolha_bb(self):
        configs = [
            {"texto": "BB Modelo 1 (Padrão)", "img": "modelo_bb1.png", "cmd": self.contabil.fluxo_bb_v1},
            {"texto": "BB Modelo 2 (Digital)", "img": "modelo_bb2.png", "cmd": self.contabil.fluxo_bb_v2}
        ]
        self.criar_tela_multi_modelos("BANCO DO BRASIL", "#fdb913", configs)

    def tela_escolha_xp(self):
        self.construir_tela_unico_modelo("XP Investimentos", "XP.png", "#000000", self.contabil.fluxo_xp)

    def tela_escolha_inter(self):
        self.construir_tela_unico_modelo("Banco Inter", "INTER.png", "#FF7A00", self.contabil.fluxo_inter)

    def tela_escolha_sicoob(self):
        configs = [
            {"texto": "Sicoob Celular (App)", "img": "sicoob_celular.png", "cmd": self.contabil.fluxo_sicoob_celular},
            {"texto": "Sicoob PDF (Desktop)", "img": "sicoob_pdf.png", "cmd": self.contabil.fluxo_sicoob_pdf}
        ]
        self.criar_tela_multi_modelos("SICOOB", "#00ae9d", configs)

    def tela_contabil(self):
        self.limpar_tela()

        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.carregar_logo(f_l)

        f_log_area = ctk.CTkFrame(self.container)
        f_log_area.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(f_log_area, text="Log de Processamento:", font=("Arial", 12, "bold")).pack(anchor="w", padx=10)
        self.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=8, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(padx=10, pady=5, fill="x")
        isolar_scroll_mouse(self.txt_log)

        f_b = ctk.CTkFrame(self.container, fg_color="transparent")
        f_b.pack(pady=20)

        btn_w = 140
        btn_h = 40
        f_font = ("Arial", 12, "bold")

        f_b1 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b1.pack(pady=10)
        ctk.CTkButton(f_b1, text="Ailos", command=self.tela_escolha_ailos, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#005A9C", hover_color="#003d6b").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Banco do Brasil", command=self.tela_escolha_bb, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#fdb913", hover_color="#c99106").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Banco Inter", command=self.tela_escolha_inter, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#FF7A00", hover_color="#CC6200").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Bradesco", command=self.tela_escolha_bradesco, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#cc092f", hover_color="#99061f").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="C6 Bank", command=self.tela_escolha_c6, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#242424", hover_color="#141414").pack(side="left", padx=10)
        ctk.CTkButton(f_b1, text="Caixa", command=self.tela_escolha_caixa, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#005CA9", hover_color="#00407a").pack(side="left", padx=10)


        f_b2 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b2.pack(pady=10)
        ctk.CTkButton(f_b2, text="Cresol", command=self.tela_escolha_cresol, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#006B3F", hover_color="#004529").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="iFood", command=self.tela_escolha_ifood, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#EA1D2C", hover_color="#b3121f").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="InfinitePay", command=self.tela_escolha_infinitepay, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#5A2D82", hover_color="#452263").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="Itaú", command=self.tela_escolha_itau, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#EC7000", hover_color="#D35400").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="MagaluPay", command=self.tela_escolha_magalupay, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#0086FF", hover_color="#006bcf").pack(side="left", padx=10)
        ctk.CTkButton(f_b2, text="Mercado Pago", command=self.tela_escolha_mercadopago, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#00B1EA", hover_color="#008CBA").pack(side="left", padx=10)

        f_b3 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b3.pack(pady=10)
        ctk.CTkButton(f_b3, text="Nubank", command=self.tela_escolha_nubank, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#8A05BE", hover_color="#6B0394").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="PagBank", command=self.tela_escolha_pagbank, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#8BC34A", hover_color="#649131").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Rendimento", command=self.tela_escolha_rendimento, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#004A93", hover_color="#00366e").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Santander", command=self.tela_escolha_santander, width=btn_w, height=btn_h,
                      font=f_font, fg_color="#ec0000", hover_color="#b30000").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Sicoob", command=self.tela_escolha_sicoob, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#00ae9d", hover_color="#008073").pack(side="left", padx=10)
        ctk.CTkButton(f_b3, text="Sicredi", command=self.tela_escolha_sicredi, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#32BC43", hover_color="#248a31").pack(side="left", padx=10)


        f_b4 = ctk.CTkFrame(f_b, fg_color="transparent")
        f_b4.pack(pady=20)
        ctk.CTkButton(f_b4, text="Stone", command=self.tela_escolha_stone, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#00A868", hover_color="#007a4c").pack(side="left", padx=10)
        ctk.CTkButton(f_b4, text="XP", command=self.tela_escolha_xp, width=btn_w, height=btn_h, font=f_font,
                      fg_color="#000000", hover_color="#333333").pack(side="left", padx=10)
        ctk.CTkButton(f_b4, text="Excel > OFX", command=lambda: self.contabil.gerar_ofx(self.log_msg), width=btn_w,
                      height=btn_h, font=f_font, fg_color="#7f8c8d", hover_color="#576162").pack(side="left", padx=10)
        ctk.CTkButton(f_b4, text="Sanitizar OFX Caixa",
                      command=lambda: self.contabil.fluxo_sanitizar_ofx_caixa(self.log_msg, None), width=btn_w,
                      height=btn_h, font=f_font, fg_color="#005CA9", hover_color="#00407a").pack(side="left", padx=10)
        ctk.CTkButton(f_b4, text="Voltar Menu", command=self.mostrar_menu_inicial, fg_color="gray",
                      hover_color="darkgray", width=200, height=40).pack(side="left", padx=10)

    # -------------------------------------------------------------------------
    # TELA FISCAL
    # -------------------------------------------------------------------------
    def tela_fiscal(self):
        self.limpar_tela()

        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.carregar_logo(f_l)

        f_c = ctk.CTkFrame(self.container)
        f_c.pack(fill="x", padx=40, pady=20)

        ctk.CTkLabel(f_c, text="Pasta de Saída:", font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=15, pady=15)
        self.entry_saida = ctk.CTkEntry(f_c, font=("Arial", 12), width=500)
        self.entry_saida.pack(side=tk.LEFT, padx=10)
        self.entry_saida.insert(0, self.configuracoes.get("ultimo_caminho", ""))

        ctk.CTkButton(f_c, text="Procurar", command=self.selecionar_p_f, width=100).pack(side=tk.LEFT, padx=15)

        f_log_area = ctk.CTkFrame(self.container, fg_color="transparent")
        f_log_area.pack(fill="both", expand=True, padx=40, pady=5)
        self.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=15, state='disabled', bg="#1e1e1e",
                                                 fg="white", font=("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True)
        isolar_scroll_mouse(self.txt_log)

        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)
        ctk.CTkButton(f_btns, text="▶ INICIAR PROCESSAMENTO FISCAL", command=self.exec_f_logic,
                      fg_color="#228B22", hover_color="#1e7a1e", font=("Arial", 14, "bold"), height=50, width=350).pack(
            side="left", padx=20)
        ctk.CTkButton(f_btns, text="Voltar Menu", command=self.mostrar_menu_inicial,
                      fg_color="gray", hover_color="darkgray", font=("Arial", 14), height=50, width=150).pack(
            side="left")

    def selecionar_p_f(self):
        p = filedialog.askdirectory()
        if p:
            self.entry_saida.delete(0, tk.END)
            self.entry_saida.insert(0, p)

    def exec_f_logic(self):
        path_atual = self.entry_saida.get().strip()
        if not path_atual:
            messagebox.showwarning("Atenção", "Selecione uma pasta de saída primeiro.")
            return

        resp = messagebox.askyesno("Confirmar", f"Salvar arquivos em:\n{path_atual}\n\nConfirma?")
        if not resp:
            novo = filedialog.askdirectory()
            if novo:
                self.entry_saida.delete(0, tk.END)
                self.entry_saida.insert(0, novo)
                path_atual = novo
            else:
                return

        self.salvar_config("ultimo_caminho", path_atual)
        self.fiscal.executar_fiscal(path_atual, self.log_msg)
        messagebox.showinfo("Sucesso", "Concluído.")

    def tratar_erro_callback(self, exc_type, exc_value, exc_traceback):
        erro_texto = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            caminho_log = os.path.join(self.pasta_exe, "erros.log")
            with open(caminho_log, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}]\n{erro_texto}\n")
        except Exception:
            pass
        messagebox.showerror("Erro inesperado", f"{exc_value}\n\nDetalhes salvos em erros.log")


def tratar_erro_thread(args):
    erro_texto = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    try:
        pasta_exe = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
            else os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(pasta_exe, "erros.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now()}] (thread {args.thread.name})\n{erro_texto}\n")
    except Exception:
        pass


if __name__ == "__main__":
    threading.excepthook = tratar_erro_thread
    root = ctk.CTk()
    app = SistemaUnificadoGUI(root)
    root.mainloop()