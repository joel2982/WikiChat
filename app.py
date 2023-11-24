import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import requests
import re
import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import faiss
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from streamlit_modal import Modal
from chatui import css,user_template,bot_template
from streamlit_extras.add_vertical_space import add_vertical_space
from langchain.schema.messages import HumanMessage, AIMessage

import mysql.connector

OPENAI_API_KEY=st.secrets['OPENAI_API_KEY']
host = st.secrets["HOST"]
user = st.secrets["USER"]
password = st.secrets["PASSWORD"]
database = st.secrets["DATABASE"]
port = st.secrets["PORT"]

# load_dotenv()
# host = os.getenv("HOST")
# driver = os.getenv("DRIVER")
# user = os.getenv("USER")
# password = os.getenv("PASSWORD")
# database = os.getenv("DATABASE")
# server = os.getenv("SERVER")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

config = {
    'host':host,
    'port' :port,
    'user':user,
    'password':password,
    'database':database   
}
chatdb = mysql.connector.connect(**config)

def new_session_state():
    if 'current_chat' not in st.session_state:
        st.session_state.current_chat = None
        st.session_state.conversation = None
        st.session_state.chat_history = None
        st.session_state.url = None

def get_wiki_text(url):
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'}
    pg_code = requests.get(url, headers=headers)
    soup = BeautifulSoup(markup=pg_code.text,features = 'html.parser')
    text = ''
    for page in soup.find_all('p'):
        text += page.text
    text = re.sub(r'\[[0-9]*\]','',text)
    text = re.sub(r'\[[a-z]*\]','',text)
    return text

def get_text_chunks(text):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    chunks = text_splitter.split_text(text)
    return chunks

def get_vectorstore(text_chunk):
    embeddings = OpenAIEmbeddings()
    vectorstore = faiss.FAISS.from_texts(texts=text_chunk,embedding=embeddings)
    return vectorstore

def get_conversation_chain(embeddings):
    llm = ChatOpenAI(temperature=0.0, model_name = "gpt-3.5-turbo")
    memory = ConversationBufferMemory(memory_key='chat_history', return_messages=True)
    conversation = ConversationalRetrievalChain.from_llm(
        llm = llm,
        memory = memory,
        retriever = embeddings.as_retriever()
    )
    return conversation

def delete_chat():
    sql_cmd = "DELETE FROM chat_history WHERE id = %s"
    values = str(st.session_state.current_chat)
    dml_cursor = chatdb.cursor()
    dml_cursor.execute(sql_cmd,values)
    chatdb.commit()
    st.session_state.clear()
    new_session_state()
    st.empty()

def retrieve_names(cmd):
    string = list(str(cmd.fetchall()))
    names=[]
    val = ''
    for i in string:
        if i in ' ,':
            if len(val)==0:
                continue
            elif i in ' ':
                val+=i
                continue
            names.append(val)
            val = ''
        elif i not in "''[]()":
            val+=i
    return names

def retrieve_messages(cmd):
    messages = list(cmd.fetchone()[1].replace('), H','), A').split('), A'))
    chats = []
    messages[0] = messages[0].replace('[H','')
    for i in range(0,len(messages)-1):
        if i%2 == 0:
            messages[i] = messages[i].replace('umanMessage(content=\'','')
            messages[i] = messages[i][0:-1]
            chats.append(HumanMessage(content=messages[i]))   
        else:
            messages[i] = messages[i].replace('IMessage(content=\'','')
            messages[i] = messages[i][0:-1]
            chats.append(AIMessage(content=messages[i]))
    messages[i+1] = messages[i+1][18:-3]
    chats.append(AIMessage(content=messages[i+1]))
    return chats

def chat_output():
    try:        
        for i,chat in enumerate(st.session_state.chat_history):
            if i%2 == 0:
                st.write(user_template.replace("{{MSG}}",chat.content), unsafe_allow_html=True)
            else:
                st.write(bot_template.replace("{{MSG}}",chat.content), unsafe_allow_html=True)
    except TypeError:
        pass

def handle_user_input(user_question):
    response = st.session_state.conversation(user_question)
    st.session_state.chat_history = response['chat_history']
    chat_history = str(st.session_state.chat_history)
    # Initializing a new chat in the database table 
    if len(st.session_state.chat_history) == 2:
        title = st.session_state.chat_history[0].content
        sql_cmd = "INSERT INTO chat_history (title, vs_name, chat_history) VALUES (%s, %s, %s)"
        values = (title,st.session_state.url,chat_history)
    # Updating the current chat in the database table 
    else:
        sql_cmd = "UPDATE chat_history SET chat_history = %s WHERE id = %s"
        values = (chat_history,st.session_state.current_chat)
    dml_cursor = chatdb.cursor()
    dml_cursor.execute(sql_cmd,values)
    chatdb.commit()
    # Getting the current chat id 
    if not st.session_state.current_chat:
        select_cursor = chatdb.cursor()
        sql_cmd = f"SELECT id FROM chat_history WHERE title = '{title}'"
        select_cursor.execute(sql_cmd)
        st.session_state.current_chat = select_cursor.fetchone()

def previous_chat_loader(chat):
    # retrieving chat id, chat history and the pdf name
    select_cursor = chatdb.cursor()
    sql_cmd = f"SELECT id,chat_history FROM chat_history WHERE title = '{chat}'"
    select_cursor.execute(sql_cmd)
    st.session_state.current_chat = select_cursor.fetchone()[0]
    select_cursor.execute(sql_cmd)  
    st.session_state.chat_history = retrieve_messages(select_cursor)
    sql_cmd = f"SELECT vs_name FROM chat_history WHERE title = '{chat}'"
    select_cursor.execute(sql_cmd)  
    st.session_state.url = select_cursor.fetchone()[0]

def main():
    load_dotenv()
    st.set_page_config(page_title='Chat with Wikipedia',page_icon=':globe_with_meridians:',initial_sidebar_state='collapsed')
    st.write(css, unsafe_allow_html=True)
    select_cursor = chatdb.cursor()
    select_cursor.execute("SELECT title FROM chat_history")
    chat_titles = retrieve_names(select_cursor)
    new_session_state()
    open_modal = None
    if st.session_state.chat_history == None:
        st.subheader('Chat with the Wikipedia :globe_with_meridians:')
    else:
        col1, col2 = st.columns([0.8,0.2])
        with col1:
            st.subheader('Chat with the Wikipedia :globe_with_meridians:')
        with col2:
            open_modal = st.button('Wiki Page') 
    placeholder = st.empty()
    # URL reciever
    if not st.session_state.url:
        with placeholder.form("my-form"):
            url = st.text_input("Insert the Wikipedia Link.")
            submitted = st.form_submit_button("SUBMIT")
            st.session_state.url = url
        try:
            # URL Data -> vectorstore
            if submitted and url:
                with st.spinner('Processing'):
                    #get the pdf text
                    text = get_wiki_text(url)
                    st.session_state.url = url
                    #divide the pdf text into text chunks
                    text_chunk = get_text_chunks(text)
                    #create vectorstores
                    embeddings = get_vectorstore(text_chunk)
                    #initializing conversation
                    st.session_state.conversation = get_conversation_chain(embeddings)
                    placeholder.empty()
        except:
            # Error occurs if a valid URL is not given          
            st.write(bot_template.replace("{{MSG}}","Please insert a valid URL."), unsafe_allow_html=True)

    with st.sidebar:
        col1, col2 = st.columns(2)
        with col1:
            new_chat = st.button('New Chat',use_container_width=True)
        with col2:
            del_chat = st.button('Delete Chat',use_container_width=True)
        add_vertical_space(2)
        # Previous Chats
        st.subheader("Previous Chats")
        for chat in chat_titles:
            if st.sidebar.button(chat, key=chat, use_container_width=True):
                st.session_state.clear()
                new_session_state()
                st.empty()
                previous_chat_loader(chat)
                st.rerun()
        add_vertical_space(2)
        st.write('Made with by [Joel John](https://www.linkedin.com/in/joeljohn29082002/)')

    if st.session_state.conversation:
        user_question = st.chat_input('Ask your Questions!')
        if user_question:
            handle_user_input(user_question)
            chat_output()
    elif st.session_state.chat_history:
        placeholder.empty()
        chat_output()
    
    if new_chat:
        st.session_state.clear()
        new_session_state()
        st.empty()
        st.rerun()
    elif del_chat:
        try:
            delete_chat()
        except:
            placeholder.empty()
            st.write(bot_template.replace("{{MSG}}",'Please Select the Chat to be deleted.'), unsafe_allow_html=True)           
            st.stop()
    elif open_modal:
        modal = Modal(key="Demo Key",title=' ',max_width=1200)
        with modal.container():
            st.components.v1.iframe(src=st.session_state.url, width=None, height=500, scrolling=True)
    if del_chat:
        st.rerun()
    chatdb.close() 

if __name__ == '__main__':
    main()
