FROM ubuntu:latest
FROM python:3.10
LABEL authors="Sadiqush"

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Command to run your bot (replace 'main.py' with your bot's entry point)
CMD ["python", "main.py"]