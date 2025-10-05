FROM node:18-alpine

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies (with legacy peer deps to handle conflicts)
RUN npm install --legacy-peer-deps

# Copy application code
COPY . .

# Build the application
RUN npm run build

# Install serve to run the built app
RUN npm install -g serve

# Expose port
EXPOSE 3000

# Command to serve the built app
CMD ["serve", "-s", "build", "-l", "3000"]