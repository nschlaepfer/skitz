## 🎵 Skitz Music Generator 🎵
Skitz is a Python program that uses OpenAI's GPT-4 model to generate creative and original music based on user inputs. It's important to note that the results can vary depending on the complexity and detail of your instructions. To get the best results, provide detailed instructions for the song you want to generate. If the output doesn't appear as expected, check the logs to see the chain of thought the model followed. Please be aware that using this program can be quite expensive due to the token usage of the GPT-4 model.🎼🎹🎷🎸



<p float="left">
  <img src="https://github.com/nschlaepfer/skitz/assets/44988633/86f3796a-5bc1-41fa-9f14-138a5e882ade" width="400" height="300" alt="Screenshot 2023-07-13 at 3 36 55 PM" />
  <img src="https://github.com/nschlaepfer/skitz/assets/44988633/52dc19f4-e15e-4d0a-a89f-d73633151695" width="400" height="300" alt="Screenshot 2023-07-13 at 3 37 56 PM" />
</p>

## Table of Contents

- [Pre-requisites](#pre-requisites)
- [Setup](#setup)
- [How to Use Skitz Music Generator](#how-to-use-skitz-music-generator)
- [Interactive Song Creation Guide](#interactive-song-creation-guide)
- [Future Features](#future-features)
- [Issues](#issues)
- [Contributing](#contributing)
- [Citation](#citation)
- [License](#license)

## 🚀 Pre-requisites

Before you begin, ensure you have met the following requirements:

- 💻 You have a compatible machine with Windows/MacOS/Linux operating system.
- 🐍 You have Python 3.6+ installed. You can check your Python version by running `python --version` or `python3 --version` in the terminal.
- 📦 You have `pip` installed. Pip is a package installer for Python and is included by default from Python 3.4 onwards. You can check the pip version by running `pip --version` or `pip3 --version` in the terminal.
- 🔑 You have obtained an API Key from OpenAI. If you do not have an OpenAI API Key, you can obtain it from [OpenAI's API Key Request](https://platform.openai.com/signup). Make sure to securely store this API key as it will be needed during the setup.
- 🎼 You have installed the Visual Studio Code extension [ABC Tools](https://marketplace.visualstudio.com/items?itemName=ishiharaf.abc-tools) for sheet music visualization and MIDI conversion.
- 🎶 You have a basic understanding of music theory.

## ⚙️ Setup

![Setup Guide GIF](path/to/setup_guide.gif)

The setup process involves creating a virtual environment, installing necessary Python packages, and setting up your OpenAI API key. Detailed instructions can be found [here](path/to/setup_instructions.md).

## 🎼 How to Use Skitz Music Generator

After you've set up your environment, installed the required packages, and set up your API key, you're ready to generate some music! 🎉

![How to use Guide GIF](path/to/how_to_use_guide.gif)

To run Skitz, navigate to the project directory and run the Python script `skitz.py`. During the interaction, you'll have the option to provide ABC code from another song as inspiration.

Detailed instructions can be found [here](path/to/how_to_use_guide.md).

## 🎹 Interactive Song Creation Guide

Dive into the creative process and craft a unique piece of music with Skitz Music Generator! Use the questions below as a guide during your creation process. And remember, creativity knows no bounds! Experiment with different genres, themes, and structures. Your unique musical piece is just a few prompts away! 🎶 For more assistance, check out [ChatGPT](https://chat.openai.com/) from OpenAI.



https://github.com/nschlaepfer/skitz/assets/44988633/0f0b56d3-0ec7-4ef1-9119-fa4764db1e6d



Above is a sample of what skitz can do with proper prompting.

## 📈 Future Features

Progress towards the next features can be tracked here:

- [ ] Orchestra Composer (Big Update)
- [ ] Better UI (Big Update)
- [ ] Improvements to Prompts and Integration of Weights and Biases for Prompt Logging (Big Update)
- [ ] In-House MIDI Conversion and ABC to MP3 Conversion (Small Update)
- [ ] Auto Mode: Autonomously generate music based on genre and inspiration (Small Update)

## 🚨 Issues

If you encounter any issues or have any questions, please refer to our [FAQ](path/to/faq.md) and [Troubleshooting](path/to/troubleshooting.md) guides. 

If your problem persists, please feel free to reach out for assistance.

## 💡 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change. Detailed contribution guidelines can be found [here](path/to/contributing.md). 🤝

We're always on the lookout for contributors, particularly those with a background in music. Please don't hesitate to get in touch!

## 📝 Citation

If you find this project useful for your research or if you use parts of this code, please consider citing it:

```bibtex
@misc{SkitzMusicGenerator,
  author = {Nicolas W Schlaepfer},
  title = {Skitz: A Music Generator

},
  year = {2023},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/nschlaepfer/Skitz}}
}
```

## 📝 License

[MIT](LICENSE)
