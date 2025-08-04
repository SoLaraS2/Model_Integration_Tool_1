# Model_Integration_Tool

This model is made to run locally (as of now). Follow these steps to use the tool.

- Install VS Code and Python (this was built on python 3.12.5)
- Clone this github repo into a folder of your liking
- Inside the folder, create another folder named 'files'.
- Inside 'files' upload all 21 year+scenario files (email lbezerra@nrel.gov if you need the files)
- It should look like:
  
🛠️ Tool Project
├── 🤖 Model_Integration_Tool_1
│   ├── 📁 files
│   │   └── 📄 all 21 year+scenario files
│   ├── 🐍 app.py
│   ├── 🌟 favicon.ico
│   ├── 🏠 index.html
│   ├── 📦 requirements.txt
│   └── ✨ script.js

- Now open a terminal into your cloned repo folder and run 'pip install -r requirements.txt'
- Go to extensions and download 'live server'
- In your terminal, run 'python app.py'
  - This should start your backend server
- Right-click the 'index.html' file and select open with live server, this should prompt a new window in your browser, and the tool is now working.
