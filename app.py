from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import uuid
import requests
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Importações para PostgreSQL
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Carrega variáveis de ambiente
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev_secret_key_change_in_production')
CORS(app, supports_credentials=True)

# Configurações
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
os.makedirs('/tmp', exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', '/tmp/leads.db')

class LeadManager:
    """Gerencia operações de banco de dados para leads - SQLite e PostgreSQL"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.is_postgres = db_url.startswith('postgresql://') or db_url.startswith('postgres://')
        
        if self.is_postgres and not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 não está instalado. Execute: pip install psycopg2-binary")
        
        self.init_database()
    
    def get_connection(self):
        """Retorna conexão apropriada (SQLite ou PostgreSQL)"""
        if self.is_postgres:
            # Corrige URL do postgres para postgresql se necessário
            db_url = self.db_url.replace('postgres://', 'postgresql://', 1)
            return psycopg2.connect(db_url)
        else:
            return sqlite3.connect(self.db_url)
    
    def init_database(self):
        """Inicializa as tabelas do banco"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                # PostgreSQL syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        convenio TEXT,
                        especialidade TEXT,
                        procedimento TEXT,
                        sintomas TEXT,
                        telefone TEXT,
                        email TEXT,
                        agendado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Criar índices para performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_session ON mensagens(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mensagens_timestamp ON mensagens(timestamp)')
                
            else:
                # SQLite syntax (desenvolvimento)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT UNIQUE NOT NULL,
                        nome TEXT,
                        convenio TEXT,
                        especialidade TEXT,
                        procedimento TEXT,
                        sintomas TEXT,
                        telefone TEXT,
                        email TEXT,
                        agendado BOOLEAN DEFAULT FALSE,
                        conversa_completa TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mensagens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            conn.commit()
            conn.close()
            print(f"✅ Banco {'PostgreSQL' if self.is_postgres else 'SQLite'} inicializado com sucesso")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")
            raise
    
    def create_lead(self, session_id: str) -> bool:
        """Cria um novo lead na base"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO leads (session_id) VALUES (%s) ON CONFLICT (session_id) DO NOTHING',
                    (session_id,)
                )
            else:
                cursor.execute('INSERT OR IGNORE INTO leads (session_id) VALUES (?)', (session_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao criar lead: {e}")
            return False
    
    def update_lead(self, session_id: str, data: Dict) -> bool:
        """Atualiza dados do lead"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Campos permitidos
            allowed_fields = ['nome', 'convenio', 'especialidade', 'procedimento', 'sintomas',
                            'telefone', 'email', 'agendado', 'conversa_completa']
            
            # Monta query dinâmica baseada nos campos fornecidos
            fields = []
            values = []
            for key, value in data.items():
                if key in allowed_fields:
                    if self.is_postgres:
                        fields.append(f"{key} = %s")
                    else:
                        fields.append(f"{key} = ?")
                    values.append(value)
            
            if fields:
                if self.is_postgres:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = %s"
                else:
                    query = f"UPDATE leads SET {', '.join(fields)} WHERE session_id = ?"
                values.append(session_id)
                cursor.execute(query, values)
                conn.commit()
            
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao atualizar lead: {e}")
            return False
    
    def save_message(self, session_id: str, role: str, content: str) -> bool:
        """Salva uma mensagem no histórico"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (%s, %s, %s)',
                    (session_id, role, content)
                )
            else:
                cursor.execute(
                    'INSERT INTO mensagens (session_id, role, content) VALUES (?, ?, ?)',
                    (session_id, role, content)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Erro ao salvar mensagem: {e}")
            return False
    
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Recupera histórico da conversa"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = %s ORDER BY timestamp ASC',
                    (session_id,)
                )
            else:
                cursor.execute(
                    'SELECT role, content, timestamp FROM mensagens WHERE session_id = ? ORDER BY timestamp ASC',
                    (session_id,)
                )
            
            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'role': row[0],
                    'content': row[1],
                    'timestamp': str(row[2])
                })
            conn.close()
            return messages
        except Exception as e:
            print(f"Erro ao recuperar histórico: {e}")
            return []
    
    def get_leads_stats(self) -> Dict:
        """Retorna estatísticas dos leads"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN agendado = true THEN 1 END) as leads_agendados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            else:
                cursor.execute('''
                    SELECT
                        COUNT(*) as total_leads,
                        COUNT(CASE WHEN agendado = 1 THEN 1 END) as leads_agendados,
                        COUNT(CASE WHEN nome IS NOT NULL THEN 1 END) as leads_com_nome,
                        COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as leads_com_email
                    FROM leads
                ''')
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_leads': row[0],
                'leads_agendados': row[1],
                'leads_com_nome': row[2],
                'leads_com_email': row[3],
                'taxa_agendamento': round((row[1] / row[0] * 100) if row[0] > 0 else 0, 1)
            }
        except Exception as e:
            print(f"Erro ao buscar estatísticas: {e}")
            return {'total_leads': 0, 'leads_agendados': 0, 'leads_com_nome': 0, 'leads_com_email': 0, 'taxa_agendamento': 0}

class ClinicaChatbot:
    """Chatbot de vendas para clínicas médicas"""
    
    def __init__(self, groq_api_key: str):
        self.api_key = groq_api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        
        # Prompt base - Assistente de Vendas para Clínica de Depilação a Laser
        self.system_prompt = """
# Assistente Virtual de Vendas — Laser Studio (Depilação a Laser)

---

## REGRAS INVIOLÁVEIS — LEIA ANTES DE QUALQUER COISA:

1. CONVERSA CONTÍNUA: Você está em uma conversa em andamento. NUNCA recomece do zero.
2. MEMÓRIA: Se já sabe o nome do cliente, USE-O. Nunca peça de novo.
3. NÃO REPITA perguntas já respondidas. Avance sempre.
4. Leia TODO o histórico antes de responder.
5. Se a primeira mensagem for "__inicio__", faça uma abertura calorosa e proativa — pergunte qual área interessa, sem pedir nome ainda.

---

## QUEM VOCÊ É:

Você é a Sofia, consultora de vendas do Laser Studio. Fala como uma amiga que manja muito do assunto — animada, acolhedora, direta, sem ser chata. Tom brasileiro, informal, sem palavrão, com 1-2 emojis por mensagem. Máximo 5 linhas por resposta.

---

## SEU ÚNICO OBJETIVO: AGENDAR A AVALIAÇÃO GRATUITA.

Tudo que você faz é para chegar lá. Mas o caminho é pela confiança, não pelo empurrão.

---

## ESTRATÉGIA DE VENDAS (siga esta ordem natural):

### FASE 1 — DESPERTE O DESEJO (antes de pedir qualquer dado)
- Comece com entusiasmo pelo problema que você resolve: "nunca mais depilação dolorosa todo mês!"
- Pergunte qual área incomoda mais ou qual resultado a pessoa sonha ter
- Use imagens mentais: "imagina acordar e já estar pronta, sem pensar nisso"
- Só passe para a fase 2 depois de sentir interesse genuíno

### FASE 2 — CONSTRUA CREDIBILIDADE
- Mencione que o laser é permanente (80-95% de redução após o ciclo)
- Use social proof: "a maioria das nossas clientes faz axilas + virilha + pernas e fica chocada com o resultado"
- Fale do equipamento moderno com resfriamento (pouco ou quase sem dor)
- Pergunte se já tentou a laser antes ou se tem alguma dúvida

### FASE 3 — OFEREÇA A AVALIAÇÃO (como presente, não como venda)
- "A boa notícia é que a avaliação é totalmente gratuita — você vem, conhece a clínica, tira todas as dúvidas e a gente monta um plano personalizado pra você"
- Crie leveza: sem compromisso, sem pressão
- Só depois de aceitar a avaliação, peça nome e telefone

### FASE 4 — FECHE O HORÁRIO
- Ofereça 2-3 opções de horário (não mais)
- Confirme: nome, área, data, horário
- Encerre com energia: "Vai ser incrível, [nome]! Te vejo lá 🙌"

---

## TRATAMENTO DE OBJEÇÕES:

**"Quanto custa?"**
Valor varia por área e número de sessões — por isso a avaliação gratuita existe. Mas pense assim: quantos anos gastando com cera, lâmina, pós-depilatório... o laser acaba com isso de vez. Na avaliação você sai com o valor exato, sem surpresa.

**"Dói?"**
A maioria descreve como um estalo de elástico rápido — e nosso equipamento tem resfriamento, então é bem tranquilo. Nada parecido com cera! 😄

**"Preciso pensar" / "Vou ver depois"**
Totalmente normal! Mas a avaliação é gratuita e sem compromisso — você não precisa decidir nada lá. Que tal marcar só pra conhecer? Tenho horário amanhã de manhã ou sábado à tarde.

**"Minha pele é escura / estou bronzeada"**
Ótimo ponto! Temos tecnologias específicas para todos os fototipos — inclusive pele escura e bronzeada. É exatamente por isso que fazemos a avaliação presencial: pra escolher o protocolo certo pra você.

**"Não tenho tempo"**
A avaliação leva uns 30 minutinhos — rápida e sem burocracia. Temos manhã, tarde, noite e sábado. Qual horário encaixa melhor pra você?

---

## COLETA DE DADOS (só após interesse confirmado):
- Nome completo e WhatsApp para confirmar o horário
- Se resistir: "É só pra mandar a confirmação, prometo que não tem spam 😊"

---

## CONHECIMENTO TÉCNICO (use quando perguntarem):
- Tecnologias: Alexandrite (peles claras), Nd:YAG (peles escuras), Diodo (todos os fototipos)
- Sessões: 6 a 10 por área, intervalo de 4 a 8 semanas
- Áreas: axilas, virilha, pernas, buço, costas, abdômen, braços
- Pré-sessão: não fazer cera/pinça por 4 semanas; barbear 1-2 dias antes
- Pós-sessão: evitar sol por 15 dias, hidratar, sem desodorante nas primeiras 24h (axilas)
- Contraindicações: gravidez, vitiligo ativo, isotretinoína recente, lesões na área

---

## ESCALAÇÃO PARA HUMANO:
Se o cliente estiver bravo, pedir pra falar com humano, ou após 3 objeções consecutivas:
→ "Deixa eu te conectar com nossa equipe agora. Um segundo! 😊"

---

## REGRAS FINAIS:
- Uma pergunta por vez, sempre
- Nunca prometar resultado 100% garantido
- Nunca diagnóstico médico
- Sempre encaminhar para a avaliação gratuita
- Nunca deixar o cliente ir embora sem ao menos tentar coletar o contato
"""
    
    def get_response(self, message: str, conversation_history: List[Dict]) -> str:
        """Gera resposta do chatbot usando Groq API"""
        
        # Prepara mensagens para a API
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Adiciona histórico da conversa (últimas 14 mensagens para manter contexto longo)
        recent_history = conversation_history[-14:] if len(conversation_history) > 14 else conversation_history
        for msg in recent_history:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Adiciona mensagem atual
        messages.append({"role": "user", "content": message})
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 400,
                "top_p": 0.9
            }
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
            
        except requests.exceptions.Timeout:
            return "Ops, demorei um pouco para responder. Pode repetir sua pergunta?"
        except requests.exceptions.HTTPError as e:
            print(f"Erro HTTP na API Groq: {e}")
            return "Tive um probleminha técnico. Pode tentar novamente?"
        except Exception as e:
            print(f"Erro na API Groq: {e}")
            return "Ops, tive um problema técnico. Pode repetir sua pergunta?"

# Instâncias globais
try:
    lead_manager = LeadManager(DATABASE_URL)
    chatbot = ClinicaChatbot(GROQ_API_KEY) if GROQ_API_KEY else None
    print("✅ Sistema inicializado com sucesso")
except Exception as e:
    print(f"❌ Erro na inicialização: {e}")
    lead_manager = None
    chatbot = None

@app.route('/')
def index():
    """Página principal do chat"""
    # Cria nova sessão se não existir
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        # Cria lead na base
        if lead_manager:
            lead_manager.create_lead(session['session_id'])
    
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Endpoint para processar mensagens do chat"""
    if not chatbot:
        return jsonify({'error': 'Chatbot não configurado. Verifique GROQ_API_KEY.'}), 500
    
    if not lead_manager:
        return jsonify({'error': 'Sistema de banco não configurado.'}), 500
    
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Mensagem vazia'}), 400
        
        session_id = session.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())
            session['session_id'] = session_id
            lead_manager.create_lead(session_id)
        
        # Salva mensagem do usuário
        lead_manager.save_message(session_id, 'user', user_message)
        
        # Recupera histórico (exclui a última mensagem que acabou de ser salva,
        # pois get_response já adiciona a mensagem atual separadamente)
        history = lead_manager.get_conversation_history(session_id)

        # Gera resposta do bot
        bot_response = chatbot.get_response(user_message, history[:-1])
        
        # Salva resposta do bot
        lead_manager.save_message(session_id, 'assistant', bot_response)
        
        return jsonify({
            'response': bot_response,
            'session_id': session_id
        })
        
    except Exception as e:
        print(f"Erro no chat: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/health')
def health():
    """Health check do sistema"""
    health_status = {
        'status': 'ok',
        'groq_configured': bool(GROQ_API_KEY),
        'database': 'connected' if lead_manager else 'error',
        'database_type': 'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite',
        'environment': os.getenv('FLASK_ENV', 'development')
    }
    
    if lead_manager:
        try:
            stats = lead_manager.get_leads_stats()
            health_status.update(stats)
        except:
            health_status['database'] = 'error'
    
    return jsonify(health_status)

@app.route('/admin/leads')
def admin_leads():
    """Página administrativa para ver leads capturados"""
    if not lead_manager:
        return "Sistema de banco não configurado", 500
    
    try:
        conn = lead_manager.get_connection()
        cursor = conn.cursor()
        
        if lead_manager.is_postgres:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens
                FROM leads l
                LEFT JOIN mensagens m ON l.session_id = m.session_id
                GROUP BY l.id, l.session_id, l.nome, l.convenio, l.especialidade, l.procedimento,
                         l.sintomas, l.telefone, l.email, l.agendado,
                         l.conversa_completa, l.created_at
                ORDER BY l.created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT l.*, COUNT(m.id) as total_mensagens 
                FROM leads l 
                LEFT JOIN mensagens m ON l.session_id = m.session_id 
                GROUP BY l.id 
                ORDER BY l.created_at DESC
            ''')
        
        leads = cursor.fetchall()
        conn.close()
        
        # Buscar estatísticas
        stats = lead_manager.get_leads_stats()
        
        leads_data = []
        for lead in leads:
            leads_data.append({
                'id': lead[0],
                'session_id': lead[1],
                'nome': lead[2] or 'N/A',
                'convenio': lead[3] or 'N/A',
                'especialidade': lead[4] or 'N/A',
                'procedimento': lead[5] or 'N/A',
                'sintomas': lead[6] or 'N/A',
                'telefone': lead[7] or 'N/A',
                'email': lead[8] or 'N/A',
                'agendado': 'Sim' if lead[9] else 'Não',
                'created_at': str(lead[11]),
                'total_mensagens': lead[12] if len(lead) > 12 else 0
            })
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin - Nexus AI Clínica</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    margin: 0; padding: 20px; background: #f8fafc; 
                }}
                .header {{ 
                    background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); 
                    color: white; padding: 2rem; border-radius: 12px; margin-bottom: 2rem; 
                }}
                .stats {{ 
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                    gap: 1rem; margin-bottom: 2rem; 
                }}
                .stat-card {{ 
                    background: white; padding: 1.5rem; border-radius: 12px; 
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                .stat-number {{ font-size: 2rem; font-weight: bold; color: #2563eb; }}
                .stat-label {{ color: #64748b; font-size: 0.875rem; }}
                table {{ 
                    background: white; border-collapse: collapse; width: 100%; 
                    border-radius: 12px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
                }}
                th, td {{ border: 1px solid #e2e8f0; padding: 12px; text-align: left; }}
                th {{ background-color: #f8fafc; font-weight: 600; }}
                .qualified {{ color: #059669; font-weight: bold; }}
                .not-qualified {{ color: #d97706; }}
                .back-link {{ 
                    display: inline-block; margin-top: 2rem; padding: 0.75rem 1.5rem; 
                    background: #2563eb; color: white; text-decoration: none; 
                    border-radius: 8px; transition: background 0.2s; 
                }}
                .back-link:hover {{ background: #1d4ed8; }}
                .empty-state {{ 
                    text-align: center; padding: 4rem; color: #64748b; 
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Nexus AI - Dashboard Administrativo</h1>
                <p>Gestão de pacientes e agendamentos</p>
                <p><strong>Banco:</strong> {'PostgreSQL' if lead_manager.is_postgres else 'SQLite'} |
                   <strong>Ambiente:</strong> {os.getenv('FLASK_ENV', 'development')}</p>
            </div>

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_leads']}</div>
                    <div class="stat-label">Total de Pacientes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_agendados']}</div>
                    <div class="stat-label">Agendamentos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['taxa_agendamento']}%</div>
                    <div class="stat-label">Taxa de Agendamento</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['leads_com_email']}</div>
                    <div class="stat-label">Pacientes com Email</div>
                </div>
            </div>
        """
        
        if leads_data:
            html += """
            <table>
                <tr>
                    <th>Data</th>
                    <th>Nome</th>
                    <th>Convenio</th>
                    <th>Especialidade</th>
                    <th>Procedimento</th>
                    <th>Sintomas</th>
                    <th>Telefone</th>
                    <th>Email</th>
                    <th>Agendado</th>
                    <th>Mensagens</th>
                </tr>
            """

            for lead in leads_data:
                agendado_class = 'qualified' if lead['agendado'] == 'Sim' else 'not-qualified'
                sintomas_truncado = (lead['sintomas'][:30] + '...'
                                   if len(lead['sintomas']) > 30 else lead['sintomas'])
                html += f"""
                    <tr>
                        <td>{lead['created_at'][:16]}</td>
                        <td>{lead['nome']}</td>
                        <td>{lead['convenio']}</td>
                        <td>{lead['especialidade']}</td>
                        <td>{lead['procedimento']}</td>
                        <td title="{lead['sintomas']}">{sintomas_truncado}</td>
                        <td>{lead['telefone']}</td>
                        <td>{lead['email']}</td>
                        <td class="{agendado_class}">{lead['agendado']}</td>
                        <td>{lead['total_mensagens']}</td>
                    </tr>
                """
            
            html += "</table>"
        else:
            html += """
            <div class="empty-state">
                <h3>Nenhum paciente registrado ainda</h3>
                <p>Quando alguem conversar com o chatbot, os dados aparecerao aqui.</p>
            </div>
            """
        
        html += """
            <a href="/" class="back-link">← Voltar ao chat</a>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"Erro ao carregar leads: {e}", 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    print("NEXUS AI - Assistente Virtual para Clinicas")
    print("=" * 50)
    print(f"Ambiente: {os.getenv('FLASK_ENV', 'development')}")
    print(f"Porta: {port}")
    print(f"Banco: {'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite'}")
    if GROQ_API_KEY:
        print(f"Groq API: Configurada (key: {GROQ_API_KEY[:8]}...)")
    else:
        print("❌ Groq API: GROQ_API_KEY não encontrada no ambiente!")
        print(f"   .env carregado de: {os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')}")
        print(f"   Variáveis de ambiente disponíveis: {[k for k in os.environ if 'GROQ' in k or 'API' in k]}")
    print(f"Admin: http://localhost:{port}/admin/leads")
    print(f"Chat: http://localhost:{port}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=debug)