# Use a stable Node image
FROM node:18-slim

# Set the working directory inside the container
WORKDIR /app

# Copy package files first to take advantage of Docker caching
COPY package*.json ./

# Install dependencies
RUN npm install --production

# Copy the rest of your application code
COPY . .

# Match the port in your docker-compose
EXPOSE 5000

# Start the application
CMD ["node", "index.js"]
