FROM tensorflow/tensorflow:1.15.0-gpu-py3

COPY . /AIDungeon

RUN apt-get update
RUN apt-get -y install sudo

RUN yes | ./AIDungeon/install.sh
RUN ./AIDungeon/download_model.sh
RUN pip install --user discord.py psutil

CMD ["bash", "-c", "cd /AIDungeon; python bot.py"]
