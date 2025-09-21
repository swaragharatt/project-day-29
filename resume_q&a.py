import React, { useState, useEffect, useRef } from 'react';
import { getAuth, signInAnonymously, onAuthStateChanged, signInWithCustomToken } from 'firebase/auth';
import { getFirestore, collection, addDoc, query, onSnapshot, orderBy, serverTimestamp } from 'firebase/firestore';
import { initializeApp } from 'firebase/app';

const firebaseConfig = JSON.parse(typeof __firebase_config !== 'undefined' ? __firebase_config : '{}');
const __initial_auth_token = typeof __initial_auth_token !== 'undefined' ? __initial_auth_token : null;

function App() {
  const [db, setDb] = useState(null);
  const [auth, setAuth] = useState(null);
  const [userId, setUserId] = useState(null);
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [uploadedText, setUploadedText] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [userQuestion, setUserQuestion] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isParsingPdf, setIsParsingPdf] = useState(false);
  const [fileError, setFileError] = useState('');
  const chatScroller = useRef(null);

  useEffect(() => {
    try {
      const app = initializeApp(firebaseConfig);
      const authInstance = getAuth(app);
      const dbInstance = getFirestore(app);
      setAuth(authInstance);
      setDb(dbInstance);

      const handleAuth = async () => {
        try {
          if (__initial_auth_token) {
            await signInWithCustomToken(authInstance, __initial_auth_token);
          } else {
            await signInAnonymously(authInstance);
          }
        } catch (error) {
          console.error("Firebase authentication error:", error);
        }
      };
      handleAuth();

      onAuthStateChanged(authInstance, (user) => {
        if (user) {
          setUserId(user.uid);
        } else {
          setUserId(null);
        }
        setIsAuthReady(true);
      });
    } catch (e) {
      console.error("Firebase initialization error", e);
    }
  }, []);

  useEffect(() => {
    if (isAuthReady && db && userId) {
      const q = query(collection(db, `artifacts/${typeof __app_id !== 'undefined' ? __app_id : 'default-app-id'}/users/${userId}/chat`), orderBy('timestamp'));
      const unsubscribe = onSnapshot(q, (snapshot) => {
        const messages = snapshot.docs.map(doc => ({
          id: doc.id,
          ...doc.data()
        }));
        setChatHistory(messages);
      });
      return () => unsubscribe();
    }
  }, [db, userId, isAuthReady]);

  useEffect(() => {
    if (chatScroller.current) {
      chatScroller.current.scrollTop = chatScroller.current.scrollHeight;
    }
  }, [chatHistory]);

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    setFileError('');
    if (file) {
      if (file.type === 'application/pdf') {
        setIsParsingPdf(true);
        const reader = new FileReader();
        reader.onload = async (e) => {
          const pdfData = new Uint8Array(e.target.result);
          try {
            const pdfjsLib = await import('https://mozilla.github.io/pdf.js/build/pdf.mjs');
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://mozilla.github.io/pdf.js/build/pdf.worker.mjs';
            const pdf = await pdfjsLib.getDocument({ data: pdfData }).promise;
            let fullText = '';
            for (let i = 1; i <= pdf.numPages; i++) {
              const page = await pdf.getPage(i);
              const textContent = await page.getTextContent();
              fullText += textContent.items.map(item => item.str).join(' ');
            }
            setUploadedText(fullText);
          } catch (error) {
            console.error("Error parsing PDF:", error);
          } finally {
            setIsParsingPdf(false);
          }
        };
        reader.readAsArrayBuffer(file);
      } else if (file.type === 'text/plain') {
        const reader = new FileReader();
        reader.onload = (e) => {
          setUploadedText(e.target.result);
        };
        reader.readAsText(file);
      } else {
        setFileError('Please upload a .txt or .pdf file.');
      }
    }
  };

  const generateAndAddQuestion = async (isFirstQuestion) => {
    if (!uploadedText.trim() || !userId) return;

    setIsGenerating(true);
    let systemPrompt = '';
    if (isFirstQuestion) {
        systemPrompt = "You are a professional technical recruiter. Based on the following resume content, generate a single, specific interview question to start the conversation. Use a conversational and friendly tone.";
    } else {
        const currentChat = chatHistory.map(msg => `${msg.role}: ${msg.text}`).join('\n');
        systemPrompt = `Based on the previous conversation and the provided resume, generate a single, new, specific interview question that a recruiter would ask. Do not repeat previous questions. The resume content is:\n\n${uploadedText}\n\nChat history:\n\n${currentChat}`;
    }
    
    try {
      const payload = {
        contents: [{ parts: [{ text: isFirstQuestion ? uploadedText : 'Generate the next question.' }] }],
        systemInstruction: { parts: [{ text: systemPrompt }] },
      };

      let response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key=`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const result = await response.json();
      const question = result?.candidates?.[0]?.content?.parts?.[0]?.text;
      
      const assistantMessage = { role: 'assistant', text: question || "I've run out of questions! Let's start a new chat.", timestamp: serverTimestamp() };
      await addDoc(collection(db, `artifacts/${typeof __app_id !== 'undefined' ? __app_id : 'default-app-id'}/users/${userId}/chat`), assistantMessage);
    } catch (error) {
      console.error("Error generating question:", error);
      const errorMessage = { role: 'assistant', text: "Sorry, I couldn't generate a question. Please try again.", timestamp: serverTimestamp() };
      await addDoc(collection(db, `artifacts/${typeof __app_id !== 'undefined' ? __app_id : 'default-app-id'}/users/${userId}/chat`), errorMessage);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSendMessage = async () => {
    if (!userQuestion.trim() || !userId) return;

    const userMessage = { role: 'user', text: userQuestion, timestamp: serverTimestamp() };
    await addDoc(collection(db, `artifacts/${typeof __app_id !== 'undefined' ? __app_id : 'default-app-id'}/users/${userId}/chat`), userMessage);
    setUserQuestion('');

    generateAndAddQuestion(false);
  };

  const Message = ({ message }) => {
    const isUser = message.role === 'user';
    return (
      <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
        <div className={`p-3 my-2 max-w-sm rounded-lg shadow-md ${isUser ? 'bg-purple-600 text-white' : 'bg-gray-800 text-white'}`}>
          {message.text}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-screen bg-black text-white font-sans">
      <div className="flex-grow p-6 overflow-y-auto">
        <div className="flex flex-col items-center justify-center">
          <h1 className="text-3xl font-bold mb-4 text-center">AI Portfolio Assistant</h1>
          <p className="text-sm text-center mb-6">Your personal Q&A bot for your resume and projects.</p>
        </div>

        <div className="mb-8 p-4 rounded-xl border border-purple-400 bg-black shadow-lg">
          <h2 className="text-lg font-semibold mb-2 text-purple-400">1. Upload your Resume/Portfolio</h2>
          <p className="text-xs mb-4 text-gray-400">Please upload a plain text (.txt) or PDF (.pdf) file with your resume or project details. The bot will use this content to generate questions.</p>
          <div className="flex items-center space-x-4">
            <input type="file" onChange={handleFileUpload} accept=".txt,.pdf" className="block w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-purple-800 file:text-purple-400 hover:file:bg-purple-700" />
            <button onClick={() => generateAndAddQuestion(true)} disabled={isGenerating || isParsingPdf || !uploadedText} className="px-4 py-2 text-sm font-semibold rounded-full bg-purple-600 text-white shadow-md disabled:bg-purple-900 disabled:text-gray-500 transition-colors">
              {isParsingPdf ? 'Parsing PDF...' : isGenerating ? 'Generating...' : 'Generate Questions'}
            </button>
          </div>
          {fileError && <p className="text-red-500 text-sm mt-2">{fileError}</p>}
        </div>

        <div className="flex-grow flex flex-col p-4 rounded-xl border border-purple-400 bg-black shadow-lg mb-8">
          <h2 className="text-lg font-semibold mb-2 text-purple-400">2. Chat with your Portfolio</h2>
          <p className="text-xs mb-4 text-gray-400">Answer the questions generated by the AI or ask your own follow-up questions about the document.</p>
          <div ref={chatScroller} className="flex-grow overflow-y-auto p-2 space-y-4 rounded bg-black custom-scrollbar" style={{maxHeight: '40vh'}}>
            {chatHistory.map(msg => <Message key={msg.id} message={msg} />)}
            {isGenerating && (
              <div className="flex justify-start">
                <div className="p-3 my-2 rounded-lg bg-gray-800 text-white">
                  <div className="animate-pulse flex space-x-2">
                    <div className="w-2 h-2 bg-gray-400 rounded-full"></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full"></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full"></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 p-4 bg-black border-t border-purple-700">
        <div className="flex items-center space-x-2">
          <input
            type="text"
            className="flex-grow px-4 py-2 rounded-full bg-purple-900 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Answer the question"
            value={userQuestion}
            onChange={(e) => setUserQuestion(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
            disabled={isGenerating || !uploadedText}
          />
          <button
            onClick={handleSendMessage}
            className="px-4 py-2 rounded-full bg-purple-600 text-white shadow-lg disabled:bg-purple-900 disabled:text-gray-500 transition-colors"
            disabled={isGenerating || !uploadedText || !userQuestion.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
