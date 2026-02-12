import type { NextAuthOptions } from "next-auth";
import EmailProvider from "next-auth/providers/email";
import PostgresAdapter from "@auth/pg-adapter";
import { Pool } from "pg";

// Create PostgreSQL connection pool for NextAuth
// Uses same DATABASE_URL as backend for consistency
// Sets search_path to "nextauth" schema to avoid collision with business "users" table
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
});

// Set search_path for all connections in the pool
pool.on('connect', (client) => {
  client.query('SET search_path TO nextauth, public');
});

export const authOptions: NextAuthOptions = {
  adapter: PostgresAdapter(pool),

  // Required so `next-auth/middleware` can recognize logged-in users
  session: {
    strategy: "jwt",
  },

  providers: [
    EmailProvider({
      server: process.env.EMAIL_SERVER,
      from: process.env.EMAIL_FROM,
    }),
  ],

  pages: {
    signIn: "/login",
    verifyRequest: "/login?check=1",
  },

  callbacks: {
    async jwt({ token, user }) {
      // Persist the database user id on the token
      if (user) {
        token.sub = (user as any).id;
      }
      return token;
    },
    async session({ session, token }) {
      // Expose user id on the session
      if (session.user && token?.sub) {
        (session.user as any).id = token.sub;
      }
      return session;
    },
  },
};