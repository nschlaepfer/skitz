# 🎵 Skitz Music Generator 🎵

Skitz is a Python program that uses OpenAI's GPT-4 model to generate creative and original music based on user inputs. 🎼🎹🎷🎸

## 🚀 Pre-requisites

Before you begin, ensure you have met the following requirements:

* 💻 You have a compatible machine with Windows/MacOS/Linux operating system.
* 🐍 You have Python 3.6+ installed. You can check your Python version by running `python --version` or `python3 --version` in the terminal.
* 📦 You have `pip` installed. Pip is a package installer for Python and is included by default from Python 3.4 onwards. You can check the pip version by running `pip --version` or `pip3 --version` in the terminal.
* 🔑 You have obtained an API Key from OpenAI. If you do not have an OpenAI API Key, you can obtain it from [OpenAI's API Key Request](https://platform.openai.com/signup). Make sure to securely store this API key as it will be needed during the setup.
* 🎼 You have installed the Visual Studio Code extension [ABC Tools](https://marketplace.visualstudio.com/items?itemName=ishiharaf.abc-tools) for sheet music visualization and MIDI conversion.
* 🎶 You have a basic understanding of music theory.

## ⚙️ Setup

The setup process involves creating a virtual environment, installing necessary Python packages, and setting up your OpenAI API key. 

### Virtual Environment Setup

To create a virtual environment, follow the steps based on your operating system.

#### Windows

```bash
python -m venv env
.\env\Scripts\activate
```

#### MacOS/Linux

```bash
python3 -m venv env
source env/bin/activate
```

If you're done working in the virtual environment for the moment, you can deactivate it with:

```bash
deactivate
```

### 📚 Install Required Packages

Once you have your virtual environment set up and activated, you can install the necessary Python packages by navigating to the project's root directory (where `requirements.txt` is located) and running:

```bash
pip install -r requirements.txt
```

### 🔐 Setting Up OpenAI API Key

After you have installed the necessary packages, you will need to setup your OpenAI API Key.

Create a new file named `.env` in the project root directory. Then open the file and write:

```bash
OPENAI_KEY=Your_OpenAI_API_Key
```

Replace `Your_OpenAI_API_Key` with the API key you obtained from OpenAI.

**Note: Make sure not to share or upload this file to public repositories for your security.**

## 🎼 How to Use Skitz Music Generator

After you've set up your environment, installed the required packages and set up your API key, you're ready to generate some music! 🎉

To run Skitz, navigate to the project directory and run the Python script `main.py`:

```bash
python main.py
```

Follow the interactive prompt in your terminal to generate your music. You can choose between Easy and Advanced mode based on your familiarity with music theory and desired level of customization.

After the program generates a song, it will save it as an ABC file in the `Generations` directory. 

To view and listen to your generated music, open the ABC file in Visual Studio Code with the ABC Tools extension installed. The extension will allow you to see the sheet music and convert it into a MIDI file.

## 💡 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change. 🤝

## 📝 License

[MIT](LICENSE)
